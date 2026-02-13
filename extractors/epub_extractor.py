import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup


# Tags to extract text from
TEXT_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "div"]


def extract_epub(filepath):
    """Extract text from an EPUB file using ebooklib and BeautifulSoup.

    Returns the full text as a single string.
    Raises ValueError for corrupt or empty EPUBs.
    """
    try:
        book = epub.read_epub(filepath, options={"ignore_ncx": True})
    except Exception as e:
        raise ValueError(f"Could not open EPUB: {e}")

    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")

        # Skip navigation/TOC pages
        body = soup.find("body")
        if body and body.get("class"):
            classes = " ".join(body["class"]).lower()
            if "nav" in classes or "toc" in classes:
                continue

        texts = []
        for tag in soup.find_all(TEXT_TAGS):
            text = tag.get_text(separator=" ", strip=True)
            if text:
                texts.append(text)

        if texts:
            chapters.append("\n\n".join(texts))

    if not chapters:
        raise ValueError("EPUB contains no extractable text.")

    return "\n\n".join(chapters)
