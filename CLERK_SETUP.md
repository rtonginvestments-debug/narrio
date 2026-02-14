# Clerk Authentication Setup Guide

## What Was Implemented

✅ **Backend Authentication System**
- JWT token verification using Clerk's RS256 algorithm
- Optional authentication decorators for routes
- Premium user detection via Clerk public metadata
- Job isolation - premium users' jobs are private, free tier jobs are public

✅ **Frontend Integration**
- Clerk.js SDK integrated
- Sign In/Sign Up modals
- User profile display with premium badge
- Dynamic tier messaging based on auth status
- Auth tokens automatically included in API requests

✅ **Access Control**
- Free tier: Up to 30 pages, no login required
- Premium tier: Unlimited pages, must be logged in
- Premium jobs are private to the user who created them
- Free tier jobs remain publicly accessible

## Setup Steps

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create Clerk Account & Application

1. Go to https://clerk.com and create an account
2. Create a new application
3. Choose authentication methods (Email/Password recommended)
4. Note your domain (e.g., `your-app-name.clerk.accounts.dev`)

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Copy from .env.example
cp .env.example .env
```

Edit `.env` and add your Clerk keys from the Clerk Dashboard:

```env
# From Clerk Dashboard → API Keys
CLERK_PUBLISHABLE_KEY=pk_test_XXXXX
CLERK_SECRET_KEY=sk_test_XXXXX
CLERK_JWKS_URL=https://your-domain.clerk.accounts.dev/.well-known/jwks.json

# Generate a random secret key
SECRET_KEY=your-random-secret-key-here
```

**To generate a secure SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Configure Clerk Dashboard

1. **Go to Clerk Dashboard → User & Authentication → Email, Phone, Username**
   - Enable Email authentication
   - Configure password requirements

2. **Go to Clerk Dashboard → Customization**
   - Customize sign-in/sign-up appearance if desired
   - Match your brand colors

3. **Go to Clerk Dashboard → Paths (optional)**
   - Configure redirect URLs if needed

### 5. Test Locally

```bash
python app.py
```

Visit http://localhost:5000 and test:

1. **Free tier flow:**
   - Upload a file <30 pages without signing in → should work
   - Upload a file >30 pages without signing in → should show premium required error

2. **Sign up flow:**
   - Click "Get Premium" button
   - Create an account
   - Should see your name and "Sign Out" button

3. **Grant yourself premium (for testing):**
   - Go to Clerk Dashboard → Users
   - Click on your user
   - Go to "Metadata" tab
   - Under "Public metadata", add:
     ```json
     {
       "isPremium": true
     }
     ```
   - Click "Save"
   - Refresh your app → should see "Premium" badge
   - Upload a file >30 pages → should work now!

### 6. Deploy to Railway

1. **Add environment variables to Railway:**
   - Go to Railway dashboard → Your project → Variables
   - Add all variables from `.env`:
     - `CLERK_PUBLISHABLE_KEY`
     - `CLERK_SECRET_KEY`
     - `CLERK_JWKS_URL`
     - `SECRET_KEY`

2. **Configure Allowed Origins in Clerk:**
   - Go to Clerk Dashboard → API Keys → Allowed Origins
   - Add your Railway URL (e.g., `https://your-app.railway.app`)

3. **Redeploy Railway:**
   ```bash
   git add .
   git commit -m "Add Clerk authentication"
   git push
   ```

## Granting Premium Access

### Manual Method (Current)

1. User signs up on your website
2. You go to Clerk Dashboard → Users
3. Find the user and click on them
4. Go to Metadata tab
5. Add to "Public metadata":
   ```json
   {
     "isPremium": true
   }
   ```
6. User immediately has unlimited access

### Future: Stripe Integration

To automate premium grants via Stripe payments:

1. Add Stripe checkout for premium plan
2. Create webhook endpoint `/api/webhooks/stripe`
3. On successful payment, update Clerk user metadata via API:
   ```python
   import requests

   def grant_premium(user_email):
       # Find user by email in Clerk
       # Update metadata via Clerk API
       # POST https://api.clerk.com/v1/users/{user_id}
       # with {"public_metadata": {"isPremium": true}}
   ```

## File Changes Summary

**New Files:**
- `auth.py` - Authentication utilities and decorators
- `.env.example` - Environment variables template
- `CLERK_SETUP.md` - This setup guide

**Modified Files:**
- `requirements.txt` - Added PyJWT, cryptography, python-dotenv, requests
- `config.py` - Added Clerk configuration from environment
- `app.py` - Added auth decorators and job isolation
- `templates/index.html` - Added Clerk SDK and auth UI
- `static/css/style.css` - Added auth section styles
- `static/js/app.js` - Added Clerk initialization and token handling

## Security Features

✅ JWT signature verification using RS256 algorithm
✅ Token expiration validation
✅ Job isolation - users can only access their own premium jobs
✅ Environment variables for sensitive keys
✅ HTTPS required for production (enforced by Clerk)
✅ No client-side premium checks - all validation server-side

## Troubleshooting

**"Clerk not configured" message:**
- Check that `.env` file exists with correct keys
- Verify `CLERK_PUBLISHABLE_KEY` starts with `pk_`
- Verify `CLERK_SECRET_KEY` starts with `sk_`

**Sign in modal doesn't open:**
- Check browser console for errors
- Verify Clerk SDK loaded (check Network tab)
- Verify publishable key is correct

**"Authentication required" error:**
- Check that token is being sent in requests
- Verify JWKS URL is correct
- Check Clerk Dashboard → Sessions for active session

**Premium status not showing:**
- Verify metadata is set correctly in Clerk Dashboard
- Check it's in "Public metadata", not "Private metadata"
- Refresh the page after updating metadata

## Next Steps

1. ✅ Set up Clerk account
2. ✅ Configure environment variables
3. ✅ Test locally with free tier
4. ✅ Grant yourself premium and test unlimited uploads
5. ✅ Deploy to Railway with environment variables
6. 🔄 (Optional) Set up Stripe for automated payments
7. 🔄 (Optional) Customize Clerk UI to match your brand
