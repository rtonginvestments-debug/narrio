from docx import Document


def extract_docx(filepath):
    """Extract text from a Word (.docx) file.

    Returns the full text as a single string.
    Raises ValueError for corrupt or empty documents.
    """
    try:
        doc = Document(filepath)
    except Exception as e:
        raise ValueError(f"Could not open Word document: {e}")

    paragraphs = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)

    if not paragraphs:
        raise ValueError("Word document contains no extractable text.")

    return "\n\n".join(paragraphs)
