import re
import fitz  # PyMuPDF
from PIL import Image
import io

# Try to import pytesseract and verify Tesseract binary is installed
OCR_AVAILABLE = False
try:
    import pytesseract
    # Set path explicitly on Windows
    import shutil
    if not shutil.which("tesseract"):
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    pytesseract.get_tesseract_version()
    OCR_AVAILABLE = True
    print("Tesseract OCR available")
except Exception:
    print("Tesseract OCR not available — image-based PDFs will not be supported")


def _rejoin_lines(text):
    """Join hard-wrapped lines within paragraphs into continuous sentences.

    PDF text has a newline at the end of every visual line on the page.
    This merges those into flowing paragraphs while preserving real paragraph breaks
    (blank lines, lines ending with sentence-ending punctuation followed by a short next line, etc.).
    """
    lines = text.split("\n")
    paragraphs = []
    current = []

    for line in lines:
        stripped = line.strip()

        # Empty line = paragraph break
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue

        current.append(stripped)

    if current:
        paragraphs.append(" ".join(current))

    # Clean up any double spaces that may have been introduced
    return "\n\n".join(re.sub(r"  +", " ", p) for p in paragraphs)


def _extract_text_with_ocr(page):
    """Extract text from a PDF page using OCR when normal text extraction fails."""
    if not OCR_AVAILABLE:
        return None

    try:
        # Render page as image at 300 DPI for better OCR accuracy
        mat = fitz.Matrix(300/72, 300/72)  # 72 DPI is default, scale to 300 DPI
        pix = page.get_pixmap(matrix=mat)

        # Convert pixmap to PIL Image
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))

        # Perform OCR
        text = pytesseract.image_to_string(img, lang='eng')
        return text.strip()
    except Exception as e:
        print(f"OCR failed for page: {e}")
        return None


def extract_pdf(filepath):
    """Extract text from a PDF file using PyMuPDF, with OCR fallback for image-based PDFs.

    Returns the full text as a single string with paragraphs separated by double newlines.
    Lines within the same paragraph are joined to avoid TTS pauses at visual line breaks.
    Raises ValueError for empty, corrupt, or password-protected PDFs.
    """
    try:
        doc = fitz.open(filepath)
    except Exception as e:
        raise ValueError(f"Could not open PDF: {e}")

    if doc.is_encrypted:
        doc.close()
        raise ValueError("PDF is password-protected and cannot be read.")

    if doc.page_count == 0:
        doc.close()
        raise ValueError("PDF has no pages.")

    pages = []
    ocr_pages_count = 0
    total_pages = doc.page_count

    for page_num, page in enumerate(doc):
        # Try normal text extraction first
        text = page.get_text("text").strip()

        # If no text found or very little text, try OCR (only if OCR is available)
        if OCR_AVAILABLE and (not text or len(text) < 50):  # Less than 50 chars suggests image-based page
            ocr_text = _extract_text_with_ocr(page)
            if ocr_text:
                text = ocr_text
                ocr_pages_count += 1

        if text:
            pages.append(_rejoin_lines(text))

    doc.close()

    if not pages:
        if OCR_AVAILABLE:
            raise ValueError("PDF contains no extractable text (may be scanned/image-based).")
        else:
            raise ValueError("PDF contains no extractable text (may be scanned/image-based).")

    # Log OCR usage
    if ocr_pages_count > 0:
        print(f"Used OCR for {ocr_pages_count} of {total_pages} pages")

    return "\n\n".join(pages)
