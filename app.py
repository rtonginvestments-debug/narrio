import os
import re
import uuid
import time
import shutil
import threading
from flask import Flask, request, jsonify, render_template, send_file, Response, g
import json
import stripe

from config import (
    UPLOAD_FOLDER, OUTPUT_FOLDER, ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE, DEFAULT_VOICE, DEFAULT_RATE, CLEANUP_AGE,
    FREE_PAGE_LIMIT, CLERK_PUBLISHABLE_KEY, GEMINI_API_KEY,
    STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID,
)
from extractors import extract_text, get_page_count, extract_chapters
from tts import get_voices, convert_to_speech
from auth import optional_auth, require_auth, get_current_user, is_premium_user, update_clerk_metadata

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

# In-memory job tracking
jobs = {}
jobs_lock = threading.Lock()

# In-memory book tracking (chapter-based conversions)
books = {}
books_lock = threading.Lock()

MAX_CHAPTERS = 60
MAX_TOTAL_WORDS = 500_000  # word limit for "Convert All"
MAX_CONCURRENT_CHAPTERS = 3

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_summary_tokens(user_data):
    """Return (tokens_remaining, month_key) — admins get 100 (never deducted), others get 10/month."""
    import datetime
    meta = (user_data or {}).get("public_metadata", {})
    # Admin users have 100 tokens and are never deducted (month_key="" signals skip)
    if meta.get("role") == "admin":
        return 100, ""
    month_key = datetime.datetime.utcnow().strftime("%Y-%m")
    stored_month = meta.get("summarizeTokensMonth", "")
    if stored_month != month_key:
        return 10, month_key   # fresh month — full 10 tokens
    remaining = meta.get("summarizeTokens", 10)
    return remaining, month_key


def cleanup_old_files():
    """Remove files older than CLEANUP_AGE from uploads and output folders."""
    now = time.time()
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        for entry in os.listdir(folder):
            filepath = os.path.join(folder, entry)
            try:
                if os.path.isfile(filepath) and now - os.path.getmtime(filepath) > CLEANUP_AGE:
                    os.remove(filepath)
                elif os.path.isdir(filepath) and now - os.path.getmtime(filepath) > CLEANUP_AGE:
                    shutil.rmtree(filepath, ignore_errors=True)
            except OSError:
                pass

    # Clean stale book records
    with books_lock:
        stale = [bid for bid, b in books.items() if now - b["created_at"] > CLEANUP_AGE]
        for bid in stale:
            del books[bid]


def is_job_cancelled(job_id):
    """Check if a job has been cancelled."""
    with jobs_lock:
        job = jobs.get(job_id)
        return job is not None and job.get("status") == "cancelled"


def run_conversion(job_id, filepath, original_name, voice, rate):
    """Run text extraction and TTS conversion in a background thread."""
    def update_progress(percent, message):
        if is_job_cancelled(job_id):
            raise InterruptedError("Conversion cancelled.")
        with jobs_lock:
            jobs[job_id]["progress"] = round(percent, 1)
            jobs[job_id]["message"] = message

    try:
        update_progress(5, "Extracting text...")
        text = extract_text(filepath)

        if not text.strip():
            raise ValueError("No text could be extracted from the file.")

        update_progress(20, "Text extracted. Starting conversion...")

        # Generate output filename based on original name
        base_name = os.path.splitext(original_name)[0]
        output_filename = f"{job_id}_{base_name}.mp3"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)

        convert_to_speech(text, output_path, voice, rate, progress_callback=update_progress)

        # Pause at each step so the SSE (0.5s poll) can catch it
        time.sleep(0.6)
        update_progress(99, "Wrapping up...")
        time.sleep(0.6)

        # Check cancellation one final time before marking complete
        if is_job_cancelled(job_id):
            raise InterruptedError("Conversion cancelled.")

        with jobs_lock:
            jobs[job_id]["progress"] = 100
            jobs[job_id]["message"] = "Done!"
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["output_file"] = output_filename
            jobs[job_id]["download_name"] = f"{base_name}.mp3"

    except InterruptedError:
        with jobs_lock:
            jobs[job_id]["status"] = "cancelled"
            jobs[job_id]["message"] = "Conversion cancelled."
            jobs[job_id]["progress"] = 0
        # Clean up partial output
        try:
            partial = os.path.join(OUTPUT_FOLDER, f"{job_id}_{os.path.splitext(original_name)[0]}.mp3")
            os.remove(partial)
        except OSError:
            pass

    except Exception as e:
        import traceback
        print(f"[ERROR] run_conversion {job_id}: {e}", flush=True)
        traceback.print_exc()
        with jobs_lock:
            if jobs.get(job_id, {}).get("status") != "cancelled":
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = str(e)
                jobs[job_id]["progress"] = 0

    finally:
        # Clean up uploaded file
        try:
            os.remove(filepath)
        except OSError:
            pass


def run_chapter_conversion(job_id, book_id, chapter_index, chapter_text, download_name, voice, rate):
    """Run TTS conversion for a single chapter (text already extracted)."""
    def update_progress(percent, message):
        if is_job_cancelled(job_id):
            raise InterruptedError("Conversion cancelled.")
        with jobs_lock:
            jobs[job_id]["progress"] = round(percent, 1)
            jobs[job_id]["message"] = message

    try:
        if not chapter_text.strip():
            raise ValueError("Chapter has no text content.")

        update_progress(20, "Converting to speech...")

        output_filename = f"{job_id}_{download_name}"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)

        convert_to_speech(chapter_text, output_path, voice, rate, progress_callback=update_progress)

        # Pause at each step so the SSE (0.5s poll) can catch it
        time.sleep(0.6)
        update_progress(99, "Wrapping up...")
        time.sleep(0.6)

        if is_job_cancelled(job_id):
            raise InterruptedError("Conversion cancelled.")

        with jobs_lock:
            jobs[job_id]["progress"] = 100
            jobs[job_id]["message"] = "Done!"
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["output_file"] = output_filename
            jobs[job_id]["download_name"] = download_name

        with books_lock:
            if book_id in books:
                books[book_id]["chapters"][chapter_index]["status"] = "completed"

    except InterruptedError:
        with jobs_lock:
            jobs[job_id]["status"] = "cancelled"
            jobs[job_id]["message"] = "Conversion cancelled."
            jobs[job_id]["progress"] = 0
        with books_lock:
            if book_id in books:
                books[book_id]["chapters"][chapter_index]["status"] = "cancelled"
        try:
            os.remove(os.path.join(OUTPUT_FOLDER, f"{job_id}_{download_name}"))
        except OSError:
            pass

    except Exception as e:
        import traceback
        print(f"[ERROR] run_chapter_conversion {job_id} ch{chapter_index}: {e}", flush=True)
        traceback.print_exc()
        with jobs_lock:
            if jobs.get(job_id, {}).get("status") != "cancelled":
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = str(e)
                jobs[job_id]["progress"] = 0

        with books_lock:
            if book_id in books:
                books[book_id]["chapters"][chapter_index]["status"] = "error"


def run_chapter_conversion_throttled(semaphore, job_id, book_id, chapter_index, *args):
    """Wrapper that acquires semaphore before running chapter conversion.

    Polls for cancellation while waiting in the semaphore queue so that
    queued jobs can be cancelled immediately instead of waiting their turn.
    """
    # Poll for cancellation while waiting for the semaphore
    while not semaphore.acquire(timeout=0.5):
        if is_job_cancelled(job_id):
            with jobs_lock:
                jobs[job_id]["message"] = "Conversion cancelled."
                jobs[job_id]["progress"] = 0
            with books_lock:
                if book_id in books and chapter_index < len(books[book_id]["chapters"]):
                    books[book_id]["chapters"][chapter_index]["status"] = "cancelled"
            return

    try:
        # Check once more right after acquiring the semaphore
        if is_job_cancelled(job_id):
            with jobs_lock:
                jobs[job_id]["message"] = "Conversion cancelled."
                jobs[job_id]["progress"] = 0
            with books_lock:
                if book_id in books and chapter_index < len(books[book_id]["chapters"]):
                    books[book_id]["chapters"][chapter_index]["status"] = "cancelled"
            return
        run_chapter_conversion(job_id, book_id, chapter_index, *args)
    finally:
        semaphore.release()


def run_summarize(job_id, filepath, original_name, voice, rate, summary_length, is_admin=False):
    """Extract text, summarize with Claude, then convert summary to audio."""
    def update_progress(percent, message):
        if is_job_cancelled(job_id):
            raise InterruptedError("Summarization cancelled.")
        with jobs_lock:
            jobs[job_id]["progress"] = round(percent, 1)
            jobs[job_id]["message"] = message

    try:
        update_progress(5, "Extracting text...")
        text = extract_text(filepath)

        if not text.strip():
            raise ValueError("No text could be extracted from the file.")

        update_progress(20, "Text extracted. Generating AI summary...")

        # Truncate to stay comfortably within Claude's context window
        max_chars = 500_000 if is_admin else 150_000
        truncated = len(text) > max_chars
        input_text = text[:max_chars]

        # max_tokens is set tight (~1.35 tokens/word) to enforce brevity at the model level
        length_configs = {
            "short":  ("5-minute",  "5",  750,  1050),
            "medium": ("10-minute", "10", 1500, 2100),
            "long":   ("20-minute", "20", 3000, 4200),
        }
        length_label, minutes_str, target_words, max_tokens = length_configs.get(
            summary_length, length_configs["medium"]
        )

        truncation_note = (
            f" Note: only the first {max_chars:,} characters of the document were provided."
        ) if truncated else ""

        prompt = (
            f"You are an expert at turning written documents into engaging, easy-to-follow audio summaries. "
            f"You will be given a PDF document and a target length in minutes.\n\n"
            f"Follow these rules strictly:\n\n"
            f"1. CONTENT FIDELITY: Only discuss information that is explicitly stated in the document. "
            f"Do not add, infer, or fabricate any facts, claims, statistics, or quotes that are not present "
            f"in the source material. If something is unclear in the document, do not attempt to fill in gaps.\n\n"
            f"2. FULL COVERAGE: Give balanced attention to the entire document from beginning to end. Do not "
            f"disproportionately focus on the opening sections while glossing over or ignoring material from "
            f"the middle or end. Every major section, argument, and finding in the document should be represented "
            f"in the summary in proportion to its significance, regardless of where it appears in the document. "
            f"Material introduced late in the document is just as important as material introduced early.\n\n"
            f"3. OPENING: Begin by stating the title of the document exactly as it appears, then give the "
            f"listener a brief sense of what the piece is about and why it matters.\n\n"
            f"4. SYNTHESIS: Do not simply walk through the document page by page or section by section. "
            f"Instead, synthesize the material into a coherent narrative that highlights the most important "
            f"ideas, key findings, and central arguments. Connect related ideas together, even if they appear "
            f"in different parts of the document. Help the listener understand not just what was said, but why it matters.\n\n"
            f"5. KEY TAKEAWAYS: Weave the most important takeaways naturally into the summary. When a finding, "
            f"statistic, or conclusion is particularly significant, take a moment to explain its importance or "
            f"implications in plain language.\n\n"
            f"6. CLOSING: End the summary with a natural, conversational conclusion that ties everything together. "
            f"Briefly synthesize the key points and main takeaways so the listener walks away with a clear "
            f"understanding of what the document covered and what matters most. The ending should feel complete "
            f"and satisfying, not abrupt. Do not use phrases like \"in conclusion\" or \"to sum up.\" Instead, "
            f"bring the summary to a natural close the way a thoughtful conversation would wind down.\n\n"
            f"7. VOICE AND TONE: Write as if you are a knowledgeable friend explaining the document to someone "
            f"over coffee. Be warm, clear, and conversational. Avoid jargon unless the document uses it, and "
            f"when jargon appears, briefly explain it. Use natural transitions between ideas. The listener "
            f"should feel like they are having an engaging conversation, not sitting through a lecture.\n\n"
            f"8. PLAIN TEXT ONLY: Output only the spoken summary text. Do not include any stage directions, "
            f"sound cues, production notes, or formatting markers such as \"(Intro Music)\", \"(Pause)\", "
            f"\"**Bold Text**\", \"[Section Break]\", or anything similar. The output should read as natural, "
            f"continuous spoken prose.\n\n"
            f"9. STRUCTURE: Deliver the summary as a smooth, flowing narrative. Do not use bullet points, "
            f"numbered lists, headers, or section labels. Write in complete sentences and paragraphs.\n\n"
            f"10. LENGTH: The user has requested a summary of approximately {minutes_str} minutes of spoken audio. "
            f"Use roughly 150 words per minute as your guide, so aim for approximately {target_words} words. "
            f"Stop at a natural sentence boundary when you approach the limit. Do not pad or repeat yourself.{truncation_note}\n\n"
            f"11. ATTRIBUTION: When referencing claims or findings, make clear they come from the document or "
            f"its authors. Do not present the document's claims as universal truths.\n\n"
            f"Document:\n{input_text}"
        )

        api_key = os.getenv("GEMINI_API_KEY", "") or GEMINI_API_KEY
        if not api_key:
            raise ValueError(
                "AI summarization is not configured on this server. "
                "Please set the GEMINI_API_KEY environment variable."
            )

        from google import genai as _genai
        from google.genai import types as _genai_types
        client = _genai.Client(api_key=api_key)

        update_progress(25, "Generating AI summary (this may take a moment)...")

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=_genai_types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                thinking_config=_genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
        summary_text = response.text

        # Safety net: hard-truncate to target_words at a sentence boundary
        words = summary_text.split()
        if len(words) > target_words:
            truncated_text = " ".join(words[:target_words])
            # Walk back to the last sentence ending so it doesn't cut mid-sentence
            for punct in ('.', '!', '?'):
                last = truncated_text.rfind(punct)
                if last > len(truncated_text) * 0.75:
                    truncated_text = truncated_text[:last + 1]
                    break
            summary_text = truncated_text

        with jobs_lock:
            jobs[job_id]["summary_text"] = summary_text

        update_progress(50, "Summary generated. Converting to audio...")

        base_name = os.path.splitext(original_name)[0]
        output_filename = f"{job_id}_{base_name}_summary.mp3"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)

        def tts_progress(percent, msg):
            update_progress(50 + percent * 0.45, msg)

        convert_to_speech(summary_text, output_path, voice, rate, progress_callback=tts_progress)

        time.sleep(0.6)
        update_progress(99, "Wrapping up...")
        time.sleep(0.6)

        if is_job_cancelled(job_id):
            raise InterruptedError("Summarization cancelled.")

        with jobs_lock:
            jobs[job_id]["progress"] = 100
            jobs[job_id]["message"] = "Summary ready!"
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["output_file"] = output_filename
            jobs[job_id]["download_name"] = f"{base_name} - Summary.mp3"

    except InterruptedError:
        with jobs_lock:
            jobs[job_id]["status"] = "cancelled"
            jobs[job_id]["message"] = "Summarization cancelled."
            jobs[job_id]["progress"] = 0
        try:
            base = os.path.splitext(original_name)[0]
            os.remove(os.path.join(OUTPUT_FOLDER, f"{job_id}_{base}_summary.mp3"))
        except OSError:
            pass

    except Exception as e:
        import traceback
        print(f"[ERROR] run_summarize {job_id}: {e}", flush=True)
        traceback.print_exc()
        with jobs_lock:
            if jobs.get(job_id, {}).get("status") != "cancelled":
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = str(e)
                jobs[job_id]["progress"] = 0

    finally:
        try:
            os.remove(filepath)
        except OSError:
            pass


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/voices")
def api_voices():
    try:
        voices = get_voices()
        return jsonify(voices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config")
def api_config():
    """Return frontend configuration including Clerk keys."""
    # Read directly from env at request time to pick up Railway env vars
    clerk_key = os.getenv("CLERK_PUBLISHABLE_KEY", "") or CLERK_PUBLISHABLE_KEY
    stripe_pub_key = os.getenv("STRIPE_PUBLISHABLE_KEY", "") or STRIPE_PUBLISHABLE_KEY
    return jsonify({
        "clerkPublishableKey": clerk_key,
        "stripePublishableKey": stripe_pub_key,
        "freeTierLimit": FREE_PAGE_LIMIT,
    })


@app.route("/api/start-trial", methods=["POST"])
@require_auth
def api_start_trial():
    """Activate a 3-day premium trial for the current user."""
    from datetime import datetime, timedelta

    user_data = get_current_user()
    if not user_data:
        return jsonify({"error": "Authentication required."}), 401

    user_id = user_data.get("id") or user_data.get("sub")
    if not user_id:
        return jsonify({"error": "Could not determine user ID."}), 400

    public_metadata = user_data.get("public_metadata", {})

    # Don't allow restarting a trial if one already expired
    if public_metadata.get("trialExpired"):
        return jsonify({"error": "Your free trial has already been used. Create a new account to start another trial."}), 400

    # Check if a trial was already started (even if async revocation hasn't run yet)
    trial_end_str = public_metadata.get("trialEnd")
    if trial_end_str:
        try:
            trial_end_dt = datetime.fromisoformat(trial_end_str)
            if datetime.utcnow() > trial_end_dt:
                # Trial expired but trialExpired flag wasn't set yet — set it now
                update_clerk_metadata(user_id, {"isPremium": False, "trialExpired": True})
                return jsonify({"error": "Your free trial has already been used. Create a new account to start another trial."}), 400
        except (ValueError, TypeError):
            pass

    # Don't restart if already premium (permanent or active trial)
    if public_metadata.get("isPremium"):
        return jsonify({"status": "already_premium"})

    # Don't allow if a trial was already started (still active)
    if public_metadata.get("trialStart"):
        return jsonify({"status": "already_premium"})

    # Set premium with 3-day trial
    trial_end = (datetime.utcnow() + timedelta(days=3)).isoformat()
    result = update_clerk_metadata(user_id, {
        "isPremium": True,
        "trialStart": datetime.utcnow().isoformat(),
        "trialEnd": trial_end,
    })

    if not result:
        return jsonify({"error": "Failed to activate trial. Please try again."}), 500

    return jsonify({"status": "trial_started", "trialEnd": trial_end})


# --- Stripe Subscription Routes ---

@app.route("/api/create-checkout-session", methods=["POST"])
@require_auth
def api_create_checkout_session():
    """Create a Stripe Checkout Session for $2.49/mo subscription."""
    secret_key = os.getenv("STRIPE_SECRET_KEY", "") or STRIPE_SECRET_KEY
    price_id = os.getenv("STRIPE_PRICE_ID", "") or STRIPE_PRICE_ID

    if not secret_key or not price_id:
        return jsonify({"error": "Stripe is not configured."}), 500

    stripe.api_key = secret_key

    user_data = g.user
    user_id = user_data.get("id") or user_data.get("sub")
    if not user_id:
        return jsonify({"error": "Could not determine user ID."}), 400

    # Get user email for Stripe prefill
    emails = user_data.get("email_addresses", [])
    customer_email = emails[0]["email_address"] if emails else None

    try:
        # Determine base URL from request
        base_url = request.host_url.rstrip("/")

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{base_url}/?subscribed=1",
            cancel_url=f"{base_url}/",
            customer_email=customer_email,
            client_reference_id=user_id,
            subscription_data={
                "metadata": {"clerk_user_id": user_id},
            },
            metadata={"clerk_user_id": user_id},
        )

        return jsonify({"url": session.url})
    except Exception as e:
        print(f"Checkout session error: {e}", flush=True)
        return jsonify({"error": "Failed to create checkout session."}), 500


@app.route("/api/webhook/stripe", methods=["POST"])
def api_stripe_webhook():
    """Handle Stripe webhook events to sync subscription status with Clerk."""
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "") or STRIPE_WEBHOOK_SECRET
    secret_key = os.getenv("STRIPE_SECRET_KEY", "") or STRIPE_SECRET_KEY

    if not webhook_secret or not secret_key:
        return jsonify({"error": "Webhook not configured"}), 500

    stripe.api_key = secret_key
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as e:
        print(f"Stripe webhook signature verification failed: {e}", flush=True)
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event["type"]
    data_object = event["data"]["object"]

    print(f"Stripe webhook received: {event_type}", flush=True)

    if event_type == "checkout.session.completed":
        clerk_user_id = data_object.get("client_reference_id") or \
                        data_object.get("metadata", {}).get("clerk_user_id")
        if clerk_user_id:
            stripe_customer_id = data_object.get("customer")
            stripe_subscription_id = data_object.get("subscription")
            update_clerk_metadata(clerk_user_id, {
                "isPremium": True,
                "trialEnd": None,
                "trialExpired": None,
                "subscriptionStatus": "active",
                "stripeCustomerId": stripe_customer_id,
                "stripeSubscriptionId": stripe_subscription_id,
            })
            print(f"Activated premium for user {clerk_user_id}", flush=True)

    elif event_type == "customer.subscription.deleted":
        clerk_user_id = data_object.get("metadata", {}).get("clerk_user_id")
        if clerk_user_id:
            update_clerk_metadata(clerk_user_id, {
                "isPremium": False,
                "subscriptionStatus": "canceled",
            })
            print(f"Revoked premium for user {clerk_user_id} (subscription canceled)", flush=True)

    elif event_type == "customer.subscription.updated":
        clerk_user_id = data_object.get("metadata", {}).get("clerk_user_id")
        status = data_object.get("status")  # active, past_due, canceled, unpaid, etc.
        if clerk_user_id and status:
            is_active = status == "active"
            update_clerk_metadata(clerk_user_id, {
                "isPremium": is_active,
                "subscriptionStatus": status,
            })
            print(f"Updated subscription status for user {clerk_user_id}: {status}", flush=True)

    return jsonify({"received": True}), 200


@app.route("/api/debug-auth")
@optional_auth
def api_debug_auth():
    """DEBUG: Check auth status. Remove after testing."""
    user_data = get_current_user()
    is_premium = is_premium_user(user_data) if user_data else False
    return jsonify({
        "has_auth_header": bool(request.headers.get("Authorization")),
        "user_data_found": user_data is not None,
        "is_premium": is_premium,
        "user_keys": list(user_data.keys()) if user_data else None,
        "public_metadata": user_data.get("public_metadata") if user_data else None,
    })


@app.route("/api/test-voice", methods=["POST"])
def api_test_voice():
    """Generate a short test clip for the selected voice."""
    voice = request.form.get("voice", DEFAULT_VOICE)

    # Extract the first name (e.g. "Aria" from "en-US-AriaNeural")
    parts = voice.split("-")
    short_name = parts[-1].replace("Neural", "").replace("Multilingual", "") if len(parts) >= 3 else voice

    test_text = f"Hi, welcome to Narrio. I'm {short_name}, this is my reading voice."

    test_id = str(uuid.uuid4())
    output_path = os.path.join(OUTPUT_FOLDER, f"test_{test_id}.mp3")

    try:
        convert_to_speech(test_text, output_path, voice, "+0%")
        response = send_file(output_path, mimetype="audio/mpeg")

        # Clean up after sending
        @response.call_on_close
        def _cleanup():
            try:
                os.remove(output_path)
            except OSError:
                pass

        return response
    except Exception as e:
        try:
            os.remove(output_path)
        except OSError:
            pass
        return jsonify({"error": str(e)}), 500


@app.route("/api/estimate", methods=["POST"])
@optional_auth
def api_estimate():
    """Extract text from uploaded file and return word count + time estimates.

    Does NOT save the file or start any conversion.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF, EPUB, and Word files are supported."}), 400

    # Get current user and check premium status
    user_data = get_current_user()
    is_premium = is_premium_user(user_data) if user_data else False

    # Save to a temp file for extraction
    temp_id = str(uuid.uuid4())
    ext = file.filename.rsplit(".", 1)[1].lower()
    temp_path = os.path.join(UPLOAD_FOLDER, f"est_{temp_id}.{ext}")
    file.save(temp_path)

    try:
        # Get page count (used for free-tier check and response)
        page_count = None
        try:
            page_count = get_page_count(temp_path)
        except Exception:
            pass

        # Enforce free-tier page limit
        if not is_premium and page_count is not None:
            if page_count > FREE_PAGE_LIMIT:
                return jsonify({
                    "error": f"This file has {page_count} pages, which exceeds the free limit of {FREE_PAGE_LIMIT} pages. Get Premium for unlimited pages!",
                    "requiresPremium": True,
                }), 400

        text = extract_text(temp_path)
        word_count = len(text.split())
        estimated_audio_minutes = round(word_count / 150, 1)
        estimated_processing_minutes = round(word_count / 2000, 1)

        return jsonify({
            "word_count": word_count,
            "estimated_audio_minutes": estimated_audio_minutes,
            "estimated_processing_minutes": estimated_processing_minutes,
            "page_count": page_count,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@app.route("/api/convert", methods=["POST"])
@optional_auth
def api_convert():
    # Run cleanup on each conversion request
    cleanup_old_files()

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF and EPUB files are supported."}), 400

    voice = request.form.get("voice", DEFAULT_VOICE)
    rate = request.form.get("rate", DEFAULT_RATE)

    # Get current user and check premium status
    user_data = get_current_user()
    is_premium = is_premium_user(user_data) if user_data else False
    user_id = (user_data.get("id") or user_data.get("sub")) if user_data else None

    # DEBUG: trace auth flow
    import sys
    auth_header = request.headers.get("Authorization", "")
    print(f"[DEBUG] Auth header present: {bool(auth_header)}, starts with Bearer: {auth_header[:15] if auth_header else 'N/A'}", file=sys.stderr, flush=True)
    print(f"[DEBUG] user_data: {user_data is not None}, is_premium: {is_premium}, user_id: {user_id}", file=sys.stderr, flush=True)
    if user_data:
        print(f"[DEBUG] user_data keys: {list(user_data.keys())}", file=sys.stderr, flush=True)
        print(f"[DEBUG] public_metadata: {user_data.get('public_metadata', 'NOT FOUND')}", file=sys.stderr, flush=True)

    # Save uploaded file
    job_id = str(uuid.uuid4())
    ext = file.filename.rsplit(".", 1)[1].lower()
    upload_path = os.path.join(UPLOAD_FOLDER, f"{job_id}.{ext}")
    file.save(upload_path)

    # Enforce free-tier page limit (skip for premium users)
    if not is_premium:
        try:
            page_count = get_page_count(upload_path)
            if page_count > FREE_PAGE_LIMIT:
                os.remove(upload_path)
                return jsonify({
                    "error": f"This file has {page_count} pages, which exceeds the free limit of {FREE_PAGE_LIMIT} pages. Get Premium for unlimited pages!",
                    "requiresPremium": True
                }), 400
        except ValueError:
            pass  # unsupported type already caught above
        except Exception:
            pass  # don't block conversion if page counting fails

    # Initialize job
    with jobs_lock:
        jobs[job_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Starting...",
            "output_file": None,
            "download_name": None,
            "user_id": user_id,
            "is_premium": is_premium,
        }

    # Start background conversion
    thread = threading.Thread(
        target=run_conversion,
        args=(job_id, upload_path, file.filename, voice, rate),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


# ---------------------------------------------------------------------------
# Chapter-based endpoints (premium only)
# ---------------------------------------------------------------------------

@app.route("/api/analyze", methods=["POST"])
@require_auth
def api_analyze():
    """Upload a book and analyze its chapters. Premium only."""
    user_data = get_current_user()
    if not is_premium_user(user_data):
        return jsonify({"error": "Premium account required for chapter analysis."}), 403

    user_id = user_data.get("id") or user_data.get("sub")

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else ""
    if ext not in ("pdf", "epub"):
        return jsonify({"error": "Chapter detection only supports PDF and EPUB files."}), 400

    voice = request.form.get("voice", DEFAULT_VOICE)
    rate = request.form.get("rate", DEFAULT_RATE)
    segments_json = request.form.get("segments")
    segment_method = request.form.get("segment_method")   # "audio_length" or "page_count"
    segment_value = request.form.get("segment_value")      # minutes or pages

    # Save uploaded file
    book_id = str(uuid.uuid4())
    upload_path = os.path.join(UPLOAD_FOLDER, f"{book_id}.{ext}")
    file.save(upload_path)

    if segment_method and segment_value:
        # --- Auto-segmentation by audio length or page count (EPUB + PDF) ---
        if ext not in ("epub", "pdf"):
            os.remove(upload_path)
            return jsonify({"error": "Auto-segmentation is only supported for PDF and EPUB files."}), 400

        try:
            seg_val = int(segment_value)
        except (ValueError, TypeError):
            os.remove(upload_path)
            return jsonify({"error": "Segment value must be a positive integer."}), 400

        if seg_val < 1:
            os.remove(upload_path)
            return jsonify({"error": "Segment value must be a positive integer."}), 400

        # Calculate target words per segment
        if segment_method == "audio_length":
            target_words = seg_val * 150  # 150 words per minute
        elif segment_method == "page_count":
            target_words = seg_val * 250  # 250 words per page
        else:
            os.remove(upload_path)
            return jsonify({"error": "Invalid segment method."}), 400

        try:
            import re as _re
            from extractors import _clean_for_tts

            _sent_re = _re.compile(r'(?<=[.!?])\s+')
            all_sentences = []  # list of (text, word_count)

            if ext == "epub":
                import ebooklib as _ebooklib
                from ebooklib import epub as _epub_lib
                from bs4 import BeautifulSoup as _BS4
                from extractors.epub_extractor import TEXT_TAGS

                epub_book = _epub_lib.read_epub(upload_path, options={"ignore_ncx": True})
                for item in epub_book.get_items():
                    if item.get_type() == _ebooklib.ITEM_DOCUMENT:
                        html = item.get_content().decode("utf-8", errors="ignore")
                        soup = _BS4(html, "html.parser")
                        body = soup.find("body")
                        if body and body.get("class"):
                            classes = " ".join(body["class"]).lower()
                            if "nav" in classes or "toc" in classes:
                                continue
                        for tag in soup.find_all(TEXT_TAGS):
                            t = tag.get_text(separator=" ", strip=True)
                            if not t:
                                continue
                            for sent in _sent_re.split(t):
                                sent = sent.strip()
                                if sent:
                                    wc = len(sent.split())
                                    if wc > 0:
                                        all_sentences.append((sent, wc))
            else:
                # PDF — extract text page by page, split into sentences
                import fitz as _fitz
                from extractors.pdf_extractor import _rejoin_lines

                doc = _fitz.open(upload_path)
                for page in doc:
                    text = page.get_text("text").strip()
                    if not text:
                        continue
                    text = _rejoin_lines(text)
                    for sent in _sent_re.split(text):
                        sent = sent.strip()
                        if sent:
                            wc = len(sent.split())
                            if wc > 0:
                                all_sentences.append((sent, wc))
                doc.close()

            # Group sentences into segments by word count target
            chapters = []
            current_texts = []
            current_words = 0
            part_number = 1

            for sent_text, sent_words in all_sentences:
                current_texts.append(sent_text)
                current_words += sent_words

                if current_words >= target_words:
                    raw_text = " ".join(current_texts)
                    text_clean = _clean_for_tts(raw_text)
                    chapters.append({
                        "index": len(chapters),
                        "section_type": "chapter",
                        "chapter_number": None,
                        "title": f"Part {part_number}",
                        "chapter_label": "",
                        "text": raw_text,
                        "text_clean": text_clean,
                        "page_start": None,
                        "page_end": None,
                        "word_count": current_words,
                        "estimated_minutes": round(current_words / 150, 1),
                    })
                    part_number += 1
                    current_texts = []
                    current_words = 0

            # Final remaining text becomes the last segment
            if current_texts:
                raw_text = " ".join(current_texts)
                text_clean = _clean_for_tts(raw_text)
                chapters.append({
                    "index": len(chapters),
                    "section_type": "chapter",
                    "chapter_number": None,
                    "title": f"Part {part_number}",
                    "chapter_label": "",
                    "text": raw_text,
                    "text_clean": text_clean,
                    "page_start": None,
                    "page_end": None,
                    "word_count": current_words,
                    "estimated_minutes": round(current_words / 150, 1),
                })

            if not chapters:
                os.remove(upload_path)
                return jsonify({"error": "No extractable text found."}), 400

            detection_method = "manual"

        except ValueError as e:
            os.remove(upload_path)
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            os.remove(upload_path)
            return jsonify({"error": f"Failed to create segments: {e}"}), 500

    elif segments_json:
        # --- Manual segment mode (PDF and EPUB) ---
        try:
            segments = json.loads(segments_json)
        except (json.JSONDecodeError, TypeError):
            os.remove(upload_path)
            return jsonify({"error": "Invalid segments data."}), 400

        if not isinstance(segments, list) or len(segments) == 0:
            os.remove(upload_path)
            return jsonify({"error": "At least one segment is required."}), 400

        try:
            from extractors import _clean_for_tts

            if ext == "pdf":
                import fitz as manual_fitz
                from extractors.chapter_splitter import _pages_text

                doc = manual_fitz.open(upload_path)
                total_items = doc.page_count
                unit_label = "pages"
            else:
                # EPUB — get spine items
                import ebooklib
                from ebooklib import epub as epub_lib
                from bs4 import BeautifulSoup as BS4

                epub_book = epub_lib.read_epub(upload_path, options={"ignore_ncx": True})
                spine_items = [
                    item for item in epub_book.get_items()
                    if item.get_type() == ebooklib.ITEM_DOCUMENT
                ]
                total_items = len(spine_items)
                unit_label = "sections"

            chapters = []
            for i, seg in enumerate(segments):
                name = seg.get("name", "").strip()
                start_idx = seg.get("start_page")
                end_idx = seg.get("end_page")

                if not name or start_idx is None or end_idx is None:
                    if ext == "pdf":
                        doc.close()
                    os.remove(upload_path)
                    return jsonify({"error": f"Segment {i+1}: all fields are required."}), 400

                start_idx = int(start_idx)
                end_idx = int(end_idx)

                if start_idx < 1 or end_idx < 1:
                    if ext == "pdf":
                        doc.close()
                    os.remove(upload_path)
                    return jsonify({"error": f"Segment {i+1}: values must be at least 1."}), 400

                if start_idx > total_items or end_idx > total_items:
                    if ext == "pdf":
                        doc.close()
                    os.remove(upload_path)
                    return jsonify({"error": f"Segment {i+1}: values exceed document length ({total_items} {unit_label})."}), 400

                if start_idx > end_idx:
                    if ext == "pdf":
                        doc.close()
                    os.remove(upload_path)
                    return jsonify({"error": f"Segment {i+1}: start cannot be greater than end."}), 400

                # Extract text based on file type
                if ext == "pdf":
                    raw_text = _pages_text(doc, start_idx - 1, end_idx)
                else:
                    # EPUB: extract text from spine items in range (1-indexed to 0-indexed)
                    texts = []
                    for si in range(start_idx - 1, end_idx):
                        item = spine_items[si]
                        html = item.get_content().decode("utf-8", errors="ignore")
                        soup = BS4(html, "html.parser")
                        for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "div"]):
                            t = tag.get_text(separator=" ", strip=True)
                            if t:
                                texts.append(t)
                    raw_text = "\n\n".join(texts)

                text_clean = _clean_for_tts(raw_text)
                word_count = len(raw_text.split())

                chapters.append({
                    "index": i,
                    "section_type": "chapter",
                    "chapter_number": None,
                    "title": name,
                    "chapter_label": "",
                    "text": raw_text,
                    "text_clean": text_clean,
                    "page_start": start_idx,
                    "page_end": end_idx,
                    "word_count": word_count,
                    "estimated_minutes": round(word_count / 150, 1),
                })

            if ext == "pdf":
                doc.close()
            detection_method = "manual"

        except ValueError as e:
            os.remove(upload_path)
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            os.remove(upload_path)
            return jsonify({"error": f"Failed to create segments: {e}"}), 500

    else:
        # --- Auto-detection mode (existing flow) ---
        try:
            chapters, detection_method = extract_chapters(upload_path)
        except ValueError as e:
            os.remove(upload_path)
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            os.remove(upload_path)
            return jsonify({"error": f"Failed to analyze book: {e}"}), 500

    # Guardrail: cap at MAX_CHAPTERS
    if len(chapters) > MAX_CHAPTERS:
        chapters = chapters[:MAX_CHAPTERS]
        for i, ch in enumerate(chapters):
            ch["index"] = i

    # Create cache directory and write chapter texts to disk
    cache_dir = os.path.join(UPLOAD_FOLDER, book_id)
    os.makedirs(cache_dir, exist_ok=True)

    chapter_meta = []
    for ch in chapters:
        # Write cleaned text to individual file
        txt_path = os.path.join(cache_dir, f"chapter_{ch['index']:02d}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(ch["text_clean"])

        chapter_meta.append({
            "index": ch["index"],
            "title": ch["title"],
            "chapter_label": ch["chapter_label"],
            "word_count": ch["word_count"],
            "estimated_minutes": ch["estimated_minutes"],
            "page_start": ch.get("page_start"),
            "page_end": ch.get("page_end"),
            "job_id": None,
            "status": "pending",
        })

    # Write book.json metadata
    book_json = {
        "filename": file.filename,
        "detection_method": detection_method,
        "chapters": chapter_meta,
    }
    with open(os.path.join(cache_dir, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book_json, f)

    # Store book record in memory (metadata only, no text)
    with books_lock:
        books[book_id] = {
            "user_id": user_id,
            "filename": file.filename,
            "upload_path": upload_path,
            "cache_dir": cache_dir,
            "detection_method": detection_method,
            "chapters": chapter_meta,
            "voice": voice,
            "rate": rate,
            "created_at": time.time(),
        }

    return jsonify({
        "book_id": book_id,
        "filename": file.filename,
        "chapter_count": len(chapter_meta),
        "detection_method": detection_method,
        "chapters": [
            {
                "index": ch["index"],
                "title": ch["title"],
                "chapter_label": ch["chapter_label"],
                "word_count": ch["word_count"],
                "estimated_minutes": ch["estimated_minutes"],
                "page_start": ch["page_start"],
                "page_end": ch["page_end"],
            }
            for ch in chapter_meta
        ],
    })


@app.route("/api/convert-chapter", methods=["POST"])
@require_auth
def api_convert_chapter():
    """Convert a single chapter to MP3. Premium only."""
    user_data = get_current_user()
    if not is_premium_user(user_data):
        return jsonify({"error": "Premium account required."}), 403

    user_id = user_data.get("id") or user_data.get("sub")

    data = request.get_json(silent=True) or {}
    book_id = data.get("book_id") or request.form.get("book_id")
    chapter_index = data.get("chapter_index")
    if chapter_index is None:
        chapter_index = request.form.get("chapter_index")
    if chapter_index is not None:
        chapter_index = int(chapter_index)

    if not book_id or chapter_index is None:
        return jsonify({"error": "book_id and chapter_index are required."}), 400

    with books_lock:
        book = books.get(book_id)

    if not book:
        return jsonify({"error": "Book not found."}), 404

    # Ownership check
    if book["user_id"] != user_id:
        return jsonify({"error": "Unauthorized access to this book."}), 403

    if chapter_index < 0 or chapter_index >= len(book["chapters"]):
        return jsonify({"error": "Invalid chapter index."}), 400

    chapter = book["chapters"][chapter_index]

    # If already processing or completed, return existing job
    if chapter["job_id"]:
        with jobs_lock:
            existing_job = jobs.get(chapter["job_id"])
        if existing_job and existing_job["status"] in ("processing", "completed"):
            return jsonify({
                "job_id": chapter["job_id"],
                "status": existing_job["status"],
            })

    # Read chapter text from cache
    txt_path = os.path.join(book["cache_dir"], f"chapter_{chapter_index:02d}.txt")
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            chapter_text = f.read()
    except FileNotFoundError:
        return jsonify({"error": "Chapter text not found. Please re-analyze the book."}), 404

    # Create job
    job_id = str(uuid.uuid4())
    base_name = os.path.splitext(book["filename"])[0]
    safe_title = re.sub(r'[^\w\s-]', '', chapter["title"])[:50].strip()
    download_name = f"{base_name} - {safe_title}.mp3"

    with jobs_lock:
        jobs[job_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Starting chapter conversion...",
            "output_file": None,
            "download_name": None,
            "user_id": user_id,
            "is_premium": True,
        }

    with books_lock:
        books[book_id]["chapters"][chapter_index]["job_id"] = job_id
        books[book_id]["chapters"][chapter_index]["status"] = "processing"

    thread = threading.Thread(
        target=run_chapter_conversion,
        args=(job_id, book_id, chapter_index, chapter_text, download_name,
              book["voice"], book["rate"]),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/convert-all-chapters", methods=["POST"])
@require_auth
def api_convert_all_chapters():
    """Convert all pending chapters for a book. Premium only."""
    user_data = get_current_user()
    if not is_premium_user(user_data):
        return jsonify({"error": "Premium account required."}), 403

    user_id = user_data.get("id") or user_data.get("sub")

    data = request.get_json(silent=True) or {}
    book_id = data.get("book_id") or request.form.get("book_id")

    if not book_id:
        return jsonify({"error": "book_id is required."}), 400

    with books_lock:
        book = books.get(book_id)

    if not book:
        return jsonify({"error": "Book not found."}), 404

    if book["user_id"] != user_id:
        return jsonify({"error": "Unauthorized access to this book."}), 403

    # Guardrail: total word limit
    total_words = sum(ch["word_count"] for ch in book["chapters"])
    if total_words > MAX_TOTAL_WORDS:
        return jsonify({
            "error": f"Total word count ({total_words:,}) exceeds the limit of {MAX_TOTAL_WORDS:,} words. Please convert chapters individually."
        }), 400

    semaphore = threading.Semaphore(MAX_CONCURRENT_CHAPTERS)
    base_name = os.path.splitext(book["filename"])[0]
    results = []

    for chapter in book["chapters"]:
        idx = chapter["index"]

        # Skip already completed or processing chapters
        if chapter["job_id"]:
            with jobs_lock:
                existing = jobs.get(chapter["job_id"])
            if existing and existing["status"] in ("processing", "completed"):
                results.append({
                    "chapter_index": idx,
                    "job_id": chapter["job_id"],
                    "status": existing["status"],
                })
                continue

        # Read chapter text
        txt_path = os.path.join(book["cache_dir"], f"chapter_{idx:02d}.txt")
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                chapter_text = f.read()
        except FileNotFoundError:
            results.append({
                "chapter_index": idx,
                "job_id": None,
                "status": "error",
            })
            continue

        job_id = str(uuid.uuid4())
        safe_title = re.sub(r'[^\w\s-]', '', chapter["title"])[:50].strip()
        download_name = f"{base_name} - {safe_title}.mp3"

        with jobs_lock:
            jobs[job_id] = {
                "status": "processing",
                "progress": 0,
                "message": "Queued...",
                "output_file": None,
                "download_name": None,
                "user_id": user_id,
                "is_premium": True,
            }

        with books_lock:
            books[book_id]["chapters"][idx]["job_id"] = job_id
            books[book_id]["chapters"][idx]["status"] = "processing"

        thread = threading.Thread(
            target=run_chapter_conversion_throttled,
            args=(semaphore, job_id, book_id, idx, chapter_text, download_name,
                  book["voice"], book["rate"]),
            daemon=True,
        )
        thread.start()

        results.append({
            "chapter_index": idx,
            "job_id": job_id,
            "status": "processing",
        })

    return jsonify({"book_id": book_id, "chapters": results})


@app.route("/api/book/<book_id>")
@require_auth
def api_book_status(book_id):
    """Get current status of all chapters for a book. Premium only."""
    user_data = get_current_user()
    if not is_premium_user(user_data):
        return jsonify({"error": "Premium account required."}), 403

    user_id = user_data.get("id") or user_data.get("sub")

    with books_lock:
        book = books.get(book_id)

    if not book:
        return jsonify({"error": "Book not found."}), 404

    if book["user_id"] != user_id:
        return jsonify({"error": "Unauthorized access to this book."}), 403

    chapter_statuses = []
    for ch in book["chapters"]:
        status_info = {
            "index": ch["index"],
            "title": ch["title"],
            "chapter_label": ch.get("chapter_label", f"#{ch['index'] + 1}"),
            "word_count": ch["word_count"],
            "estimated_minutes": ch["estimated_minutes"],
            "page_start": ch.get("page_start"),
            "page_end": ch.get("page_end"),
            "job_id": ch["job_id"],
            "status": ch["status"],
            "progress": 0,
            "message": "",
        }

        if ch["job_id"]:
            with jobs_lock:
                job = jobs.get(ch["job_id"])
            if job:
                status_info["status"] = job["status"]
                status_info["progress"] = job["progress"]
                status_info["message"] = job["message"]

        chapter_statuses.append(status_info)

    return jsonify({
        "book_id": book_id,
        "filename": book["filename"],
        "detection_method": book["detection_method"],
        "chapters": chapter_statuses,
    })


@app.route("/api/summarize", methods=["POST"])
@require_auth
def api_summarize():
    """Summarize an uploaded PDF/EPUB using Claude AI. Premium only."""
    user_data = get_current_user()
    if not is_premium_user(user_data):
        return jsonify({"error": "Premium account required for AI summarization."}), 403

    user_id = user_data.get("id") or user_data.get("sub")

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF, EPUB, and Word files are supported."}), 400

    voice = request.form.get("voice", DEFAULT_VOICE)
    rate = request.form.get("rate", DEFAULT_RATE)
    summary_length = request.form.get("summary_length", "medium")

    if summary_length not in ("short", "medium", "long"):
        return jsonify({"error": "summary_length must be short, medium, or long."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "") or GEMINI_API_KEY
    if not api_key:
        return jsonify({
            "error": "AI summarization is not available — the server is missing a GEMINI_API_KEY."
        }), 503

    job_id = str(uuid.uuid4())
    ext = file.filename.rsplit(".", 1)[1].lower()
    upload_path = os.path.join(UPLOAD_FOLDER, f"{job_id}.{ext}")
    file.save(upload_path)

    # Enforce 25-page limit for AI summaries (admins are exempt)
    is_admin = user_data.get("public_metadata", {}).get("role") == "admin"
    print(f"[SUMMARIZE] user_id={user_id} is_admin={is_admin} public_metadata={user_data.get('public_metadata', {})}", file=sys.stderr, flush=True)
    if not is_admin:
        try:
            page_count = get_page_count(upload_path)
            if page_count > 25:
                os.remove(upload_path)
                return jsonify({
                    "error": f"AI summaries are limited to files with 25 pages or fewer. This file has {page_count} pages."
                }), 400
        except Exception:
            pass  # don't block if page counting fails

    # Token cost map and check
    token_costs = {"short": 1, "medium": 2, "long": 4}
    token_cost = token_costs.get(summary_length, 1)
    tokens_remaining, month_key = get_summary_tokens(user_data)

    if tokens_remaining < token_cost:
        os.remove(upload_path)
        return jsonify({
            "error": "You're out of AI summary tokens for this month. Tokens reset on the 1st of each month.",
            "tokens_remaining": tokens_remaining,
        }), 402

    with jobs_lock:
        jobs[job_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Starting...",
            "output_file": None,
            "download_name": None,
            "user_id": user_id,
            "is_premium": True,
            "summary_text": None,
            "job_type": "summarize",
        }

    thread = threading.Thread(
        target=run_summarize,
        args=(job_id, upload_path, file.filename, voice, rate, summary_length, is_admin),
        daemon=True,
    )
    thread.start()

    # Deduct tokens from Clerk metadata (fire-and-forget; skipped for admins)
    if month_key:  # month_key == "" means admin — never deduct
        new_remaining = tokens_remaining - token_cost
        update_clerk_metadata(user_id, {
            "summarizeTokens": new_remaining,
            "summarizeTokensMonth": month_key,
        })
    else:
        new_remaining = tokens_remaining  # admin keeps 100

    return jsonify({"job_id": job_id, "tokens_remaining": new_remaining})


@app.route("/api/debug-me")
def api_debug_me():
    """Return raw user data from Clerk — for debugging metadata issues."""
    user_data = get_current_user()
    if not user_data:
        return jsonify({"error": "Not authenticated — append ?token=<your_clerk_token> to the URL"}), 401
    is_admin = user_data.get("public_metadata", {}).get("role") == "admin"
    return jsonify({
        "user_id": user_data.get("id") or user_data.get("sub"),
        "public_metadata": user_data.get("public_metadata", {}),
        "is_admin": is_admin,
        "is_premium": is_premium_user(user_data),
    })


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id):
    """Cancel a running conversion job."""
    with jobs_lock:
        job = jobs.get(job_id)

    if job is None:
        return jsonify({"error": "Job not found."}), 404

    if job["status"] not in ("processing",):
        return jsonify({"error": "Job is not running."}), 400

    with jobs_lock:
        jobs[job_id]["status"] = "cancelled"
        jobs[job_id]["message"] = "Cancelling..."

    return jsonify({"status": "cancelled"})


@app.route("/api/cancel-book/<book_id>", methods=["POST"])
@optional_auth
def api_cancel_book(book_id):
    """Cancel ALL running conversions for a book. Checks book ownership."""
    user_data = get_current_user()
    current_user_id = (user_data.get("id") or user_data.get("sub")) if user_data else None

    with books_lock:
        book = books.get(book_id)

    if not book:
        return jsonify({"error": "Book not found."}), 404

    # Check book ownership (allow if no user_id on book, i.e. unauthenticated)
    book_user_id = book.get("user_id")
    if book_user_id and current_user_id and book_user_id != current_user_id:
        return jsonify({"error": "Unauthorized."}), 403

    cancelled_count = 0
    for ch in book["chapters"]:
        job_id = ch.get("job_id")
        if not job_id:
            continue
        with jobs_lock:
            job = jobs.get(job_id)
            if job and job["status"] == "processing":
                job["status"] = "cancelled"
                job["message"] = "Cancelling..."
                cancelled_count += 1
        with books_lock:
            ch["status"] = "cancelled"

    return jsonify({"status": "cancelled", "cancelled_count": cancelled_count})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    # Job IDs are UUIDs — unguessable, so no auth check needed for progress.
    def generate():
        while True:
            with jobs_lock:
                job = jobs.get(job_id)

            if job is None:
                data = {"status": "error", "message": "Job not found.", "progress": 0}
                yield f"data: {json.dumps(data)}\n\n"
                return

            data = {
                "status": job["status"],
                "progress": job["progress"],
                "message": job["message"],
            }
            if job.get("summary_text") and job["status"] == "completed":
                data["summary_text"] = job["summary_text"]
            yield f"data: {json.dumps(data)}\n\n"

            if job["status"] in ("completed", "error", "cancelled"):
                return

            time.sleep(0.5)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@app.route("/api/download/<job_id>")
def api_download(job_id):
    # Job IDs are UUIDs — unguessable, so no auth check needed for download.
    with jobs_lock:
        job = jobs.get(job_id)

    if job is None:
        return jsonify({"error": "Job not found."}), 404

    if job["status"] != "completed":
        return jsonify({"error": "Conversion not complete."}), 400

    output_path = os.path.join(OUTPUT_FOLDER, job["output_file"])
    if not os.path.exists(output_path):
        return jsonify({"error": "Output file not found."}), 404

    return send_file(output_path, as_attachment=True, download_name=job["download_name"])


@app.route("/api/summary-pdf/<job_id>")
def api_summary_pdf(job_id):
    """Download the AI summary as a PDF file."""
    with jobs_lock:
        job = jobs.get(job_id)

    if job is None:
        return jsonify({"error": "Job not found."}), 404

    summary_text = job.get("summary_text")
    if not summary_text:
        return jsonify({"error": "No summary text available for this job."}), 400

    base_download = job.get("download_name", "Summary.mp3")
    pdf_name = base_download.replace(".mp3", ".pdf")

    try:
        from fpdf import FPDF
        import io

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_margins(20, 20, 20)

        # Title
        pdf.set_font("Helvetica", "B", 16)
        title = pdf_name.replace(".pdf", "")
        pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(6)

        # Body — sanitize to latin-1 for built-in Helvetica font
        pdf.set_font("Helvetica", size=11)
        safe_text = summary_text.encode("latin-1", errors="replace").decode("latin-1")
        pdf.multi_cell(0, 6, safe_text)

        pdf_bytes = bytes(pdf.output())
        pdf_io = io.BytesIO(pdf_bytes)
        pdf_io.seek(0)

        return send_file(
            pdf_io,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=pdf_name,
        )
    except Exception as e:
        return jsonify({"error": f"Failed to generate PDF: {e}"}), 500


if __name__ == "__main__":
    # Startup diagnostics
    clerk_key = os.getenv("CLERK_PUBLISHABLE_KEY", "")
    clerk_secret = os.getenv("CLERK_SECRET_KEY", "")
    clerk_jwks = os.getenv("CLERK_JWKS_URL", "")
    print(f"[STARTUP] CLERK_PUBLISHABLE_KEY set: {bool(clerk_key)} (len={len(clerk_key)})", flush=True)
    print(f"[STARTUP] CLERK_SECRET_KEY set: {bool(clerk_secret)} (len={len(clerk_secret)})", flush=True)
    print(f"[STARTUP] CLERK_JWKS_URL set: {bool(clerk_jwks)}", flush=True)
    print(f"[STARTUP] UPLOAD_FOLDER: {UPLOAD_FOLDER}", flush=True)
    print(f"[STARTUP] OUTPUT_FOLDER: {OUTPUT_FOLDER}", flush=True)

    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
