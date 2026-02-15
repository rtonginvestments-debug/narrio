import os
import re
import uuid
import time
import shutil
import threading
from flask import Flask, request, jsonify, render_template, send_file, Response
import json

from config import (
    UPLOAD_FOLDER, OUTPUT_FOLDER, ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE, DEFAULT_VOICE, DEFAULT_RATE, CLEANUP_AGE,
    FREE_PAGE_LIMIT, CLERK_PUBLISHABLE_KEY,
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
    return jsonify({
        "clerkPublishableKey": clerk_key,
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

    # Extract the short name (e.g. "Aria" from "en-US-AriaNeural")
    parts = voice.split("-")
    short_name = parts[-1].replace("Neural", "") if len(parts) >= 3 else voice

    test_text = (
        f"Hi there, welcome to Narrio, your personal file narrator. "
        f"I'm {short_name}. This is my reading voice."
    )

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
