import os
import re

import fitz
import ebooklib
from ebooklib import epub
from docx import Document

from .pdf_extractor import extract_pdf
from .epub_extractor import extract_epub
from .docx_extractor import extract_docx

# Marker injected between paragraphs; the TTS engine splits on it and
# writes silent MP3 frames to produce a real audible pause.
TTS_PAUSE = "TTSPAUSEBREAK"


def _clean_for_tts(text):
    """Remove footnote references and other TTS distractions."""
    # 1. Remove superscript unicode digits (⁰¹²³⁴⁵⁶⁷⁸⁹)
    text = re.sub(r'[⁰¹²³⁴⁵⁶⁷⁸⁹]+', '', text)

    # 2. Remove bracketed number references like [1], [23], [1,2], [1-3]
    text = re.sub(r'\[\d[\d,\-–\s]*\]', '', text)

    # 3. Remove bare footnote numbers glued to end of words/punctuation
    #    e.g. "word3" "sentence.12" — 1-3 digit number at end of word
    text = re.sub(r'(?:(?<=[a-zA-Z])|(?<=[a-zA-Z][.,;:!?]))\d{1,3}(?=\s|$|[.,;:!?\)])', '', text)

    # 4. Clean up any extra whitespace introduced
    text = re.sub(r'  +', ' ', text)

    # 5. Insert a pause marker between every paragraph.  The TTS engine
    #    splits on this marker and writes silent MP3 frames so the listener
    #    hears a clear break at every line break in the source text.
    paragraphs = text.split("\n\n")
    processed = []
    for p in paragraphs:
        stripped = p.strip()
        if stripped:
            processed.append(stripped)
    text = (" " + TTS_PAUSE + " ").join(processed)

    return text


def get_page_count(filepath):
    """Return an estimated page count without doing full text extraction."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        with fitz.open(filepath) as doc:
            return doc.page_count
    elif ext == ".epub":
        book = epub.read_epub(filepath, options={"ignore_ncx": True})
        return sum(
            1 for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        )
    elif ext == ".docx":
        doc = Document(filepath)
        word_count = sum(len(p.text.split()) for p in doc.paragraphs)
        return max(1, round(word_count / 250))
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def extract_text(filepath):
    """Dispatch to the correct extractor based on file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        raw = extract_pdf(filepath)
    elif ext == ".epub":
        raw = extract_epub(filepath)
    elif ext == ".docx":
        raw = extract_docx(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    return _clean_for_tts(raw)
