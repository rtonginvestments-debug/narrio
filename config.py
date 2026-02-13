import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "output")

ALLOWED_EXTENSIONS = {"pdf", "epub", "docx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

DEFAULT_VOICE = "en-US-AriaNeural"
DEFAULT_RATE = "+0%"

# Auto-cleanup files older than this (seconds)
CLEANUP_AGE = 3600  # 1 hour
