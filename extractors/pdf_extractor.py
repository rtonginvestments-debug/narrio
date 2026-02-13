import re
import fitz  # PyMuPDF


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


def extract_pdf(filepath):
    """Extract text from a PDF file using PyMuPDF.

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
    for page in doc:
        text = page.get_text("text").strip()
        if text:
            pages.append(_rejoin_lines(text))

    doc.close()

    if not pages:
        raise ValueError("PDF contains no extractable text (may be scanned/image-based).")

    return "\n\n".join(pages)
