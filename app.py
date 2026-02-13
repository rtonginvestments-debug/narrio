import os
import uuid
import time
import threading
from flask import Flask, request, jsonify, render_template, send_file, Response
import json

from config import (
    UPLOAD_FOLDER, OUTPUT_FOLDER, ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE, DEFAULT_VOICE, DEFAULT_RATE, CLEANUP_AGE,
    FREE_PAGE_LIMIT,
)
from extractors import extract_text, get_page_count
from tts import get_voices, convert_to_speech

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

# In-memory job tracking
jobs = {}
jobs_lock = threading.Lock()

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def cleanup_old_files():
    """Remove files older than CLEANUP_AGE from uploads and output folders."""
    now = time.time()
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        for filename in os.listdir(folder):
            filepath = os.path.join(folder, filename)
            try:
                if os.path.isfile(filepath) and now - os.path.getmtime(filepath) > CLEANUP_AGE:
                    os.remove(filepath)
            except OSError:
                pass


def run_conversion(job_id, filepath, original_name, voice, rate):
    """Run text extraction and TTS conversion in a background thread."""
    def update_progress(percent, message):
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

        with jobs_lock:
            jobs[job_id]["progress"] = 100
            jobs[job_id]["message"] = "Done!"
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["output_file"] = output_filename
            jobs[job_id]["download_name"] = f"{base_name}.mp3"

    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["message"] = str(e)
            jobs[job_id]["progress"] = 0

    finally:
        # Clean up uploaded file
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


@app.route("/api/convert", methods=["POST"])
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

    # Save uploaded file
    job_id = str(uuid.uuid4())
    ext = file.filename.rsplit(".", 1)[1].lower()
    upload_path = os.path.join(UPLOAD_FOLDER, f"{job_id}.{ext}")
    file.save(upload_path)

    # Enforce free-tier page limit
    try:
        page_count = get_page_count(upload_path)
        if page_count > FREE_PAGE_LIMIT:
            os.remove(upload_path)
            return jsonify({
                "error": f"This file has {page_count} pages, which exceeds the free limit of {FREE_PAGE_LIMIT} pages. Premium version with unlimited pages is coming soon!"
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
        }

    # Start background conversion
    thread = threading.Thread(
        target=run_conversion,
        args=(job_id, upload_path, file.filename, voice, rate),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
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

            if job["status"] in ("completed", "error"):
                return

            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/download/<job_id>")
def api_download(job_id):
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
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
