"""
Clerk authentication utilities for JWT verification and user management.
"""
import os
import time
import jwt
import requests
from functools import wraps
from flask import request, jsonify, g

# Cache for JWKS (JSON Web Key Set)
_jwks_cache = None

# Cache for user data from Clerk API (user_id -> {data, expires_at})
_user_cache = {}
_USER_CACHE_TTL = 60  # seconds


def get_jwks():
    """Fetch and cache Clerk's JWKS for token verification."""
    global _jwks_cache

    if _jwks_cache is not None:
        return _jwks_cache

    jwks_url = os.getenv("CLERK_JWKS_URL", "")
    if not jwks_url:
        return None

    try:
        response = requests.get(jwks_url, timeout=5)
        response.raise_for_status()
        _jwks_cache = response.json()
        return _jwks_cache
    except Exception as e:
        print(f"Failed to fetch JWKS: {e}")
        return None


def verify_clerk_token(token):
    """
    Verify and decode a Clerk JWT token using RS256 algorithm.

    Args:
        token: JWT token string

    Returns:
        dict: Decoded token payload with user data
        None: If verification fails
    """
    if not token:
        return None

    try:
        jwks = get_jwks()
        if not jwks:
            return None

        # Get the signing key from JWKS
        unverified_header = jwt.get_unverified_header(token)
        matching_key = None

        for key in jwks.get("keys", []):
            if key["kid"] == unverified_header["kid"]:
                matching_key = key
                break

        if not matching_key:
            print("No matching key found in JWKS", flush=True)
            return None

        # Convert JWK to RSA public key that PyJWT can use
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching_key)

        # Verify and decode the token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_exp": True}
        )

        return payload

    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {e}")
        return None
    except Exception as e:
        print(f"Token verification error: {e}")
        return None


def fetch_clerk_user(user_id):
    """
    Fetch full user data from Clerk Backend API, including public_metadata.
    Results are cached for 60 seconds to avoid excessive API calls.

    Args:
        user_id: Clerk user ID (from JWT 'sub' claim)

    Returns:
        dict: Full user data including public_metadata
        None: If fetch fails
    """
    now = time.time()

    # Check cache
    cached = _user_cache.get(user_id)
    if cached and cached["expires_at"] > now:
        return cached["data"]

    secret_key = os.getenv("CLERK_SECRET_KEY", "")
    if not secret_key:
        return None

    try:
        response = requests.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()

        # Cache the result
        _user_cache[user_id] = {"data": data, "expires_at": now + _USER_CACHE_TTL}

        return data
    except Exception as e:
        print(f"Failed to fetch Clerk user {user_id}: {e}")
        return None


def get_current_user():
    """
    Extract user data from the current request.
    Checks both Authorization header and query parameter (for SSE).
    Fetches full user profile from Clerk API to get public_metadata.

    Returns:
        dict: User data with public_metadata from Clerk API
        None: If no valid token found
    """
    token = None

    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # Check query parameter (for SSE which can't set headers)
    if not token:
        token = request.args.get("token")

    if not token:
        return None

    # Verify the JWT to get the user ID
    jwt_payload = verify_clerk_token(token)
    if not jwt_payload:
        return None

    user_id = jwt_payload.get("sub")
    if not user_id:
        return None

    # Fetch full user data from Clerk API (includes public_metadata)
    user_data = fetch_clerk_user(user_id)
    if user_data:
        return user_data

    # Fallback to JWT payload if API call fails
    return jwt_payload


def update_clerk_metadata(user_id, public_metadata):
    """
    Update a Clerk user's public_metadata via the Backend API.

    Args:
        user_id: Clerk user ID
        public_metadata: dict of metadata to merge

    Returns:
        dict: Updated user data, or None on failure
    """
    secret_key = os.getenv("CLERK_SECRET_KEY", "")
    if not secret_key:
        return None

    try:
        response = requests.patch(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            },
            json={"public_metadata": public_metadata},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()

        # Invalidate user cache so next fetch picks up changes
        _user_cache.pop(user_id, None)

        return data
    except Exception as e:
        print(f"Failed to update Clerk metadata for {user_id}: {e}")
        return None


def is_premium_user(user_data):
    """
    Check if a user has premium status via Clerk public metadata.
    Also checks trial expiration — if trial has expired, returns False
    and asynchronously revokes premium.

    Args:
        user_data: Decoded JWT payload

    Returns:
        bool: True if user has active premium or unexpired trial
    """
    if not user_data:
        return False

    public_metadata = user_data.get("public_metadata", {})

    # Admin users are always permanently premium
    if public_metadata.get("role") == "admin":
        return True

    if not public_metadata.get("isPremium", False):
        return False

    # Check trial expiration
    trial_end = public_metadata.get("trialEnd")
    if trial_end:
        try:
            from datetime import datetime
            end_dt = datetime.fromisoformat(trial_end)
            if datetime.utcnow() > end_dt:
                # Trial expired — revoke premium in background
                user_id = user_data.get("id") or user_data.get("sub")
                if user_id:
                    import threading
                    threading.Thread(
                        target=update_clerk_metadata,
                        args=(user_id, {"isPremium": False, "trialExpired": True}),
                        daemon=True,
                    ).start()
                    _user_cache.pop(user_id, None)
                return False
        except (ValueError, TypeError):
            pass  # Not a valid date, treat as permanent premium

    return True


def optional_auth(f):
    """
    Decorator to optionally attach authenticated user to flask.g.user.
    If no valid token, g.user will be None (does not block request).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        g.user = get_current_user()
        return f(*args, **kwargs)
    return decorated_function


def require_auth(f):
    """
    Decorator to require authentication.
    Returns 401 if no valid token is present.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated_function
