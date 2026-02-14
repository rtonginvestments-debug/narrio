"""
High-accuracy chapter detection for PDF and EPUB files.

Strategy:
  PDF: PASS 1 - Parse printed TOC pages (not PDF outline metadata)
       PASS 2 - Detect in-body headings via font-size analysis
       PASS 3 - Align TOC entries to detected heading boundaries
       Fallbacks: PDF outline -> heading-only -> page chunking

  EPUB: Spine-based detection with TOC title mapping

Output per chapter:
  index, section_type, chapter_number, title, chapter_label,
  page_start, page_end, text, word_count
"""

import os
import re
import statistics
from difflib import SequenceMatcher

import fitz
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from .pdf_extractor import _rejoin_lines
from .epub_extractor import TEXT_TAGS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_WORDS_PER_CHAPTER = 100
PAGE_CHUNK_SIZE = 20

# Written-out numbers
WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22,
    "twenty-three": 23, "twenty-four": 24, "twenty-five": 25,
    "twenty-six": 26, "twenty-seven": 27, "twenty-eight": 28,
    "twenty-nine": 29, "thirty": 30,
}

ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# Front/back matter keywords
FRONT_MATTER_WORDS = {
    "preface", "introduction", "prologue", "foreword",
    "acknowledgments", "acknowledgements", "dedication",
}
BACK_MATTER_WORDS = {
    "epilogue", "afterword", "conclusion", "bibliography",
    "glossary", "index", "notes", "appendix", "about the author",
    "about the authors", "further reading",
}


def _debug(msg):
    """Print debug message, safe for Windows console."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode(), flush=True)


# ---------------------------------------------------------------------------
# Number normalization helpers
# ---------------------------------------------------------------------------

def _roman_to_int(s):
    """Convert roman numeral to int, or None if invalid."""
    s = s.upper().strip()
    if not s or not all(c in ROMAN_VALUES for c in s):
        return None
    total = 0
    prev = 0
    for c in reversed(s):
        val = ROMAN_VALUES[c]
        if val < prev:
            total -= val
        else:
            total += val
        prev = val
    return total if 0 < total < 200 else None


def _parse_number(s):
    """Parse a number string (digit, roman, or written-out) to int or None."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    low = s.lower().replace("\u2010", "-").replace("\u2011", "-")
    if low in WORD_TO_NUM:
        return WORD_TO_NUM[low]
    r = _roman_to_int(s)
    return r


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _page_text(doc, page_num):
    """Extract and rejoin text from a single PDF page."""
    page = doc[page_num]
    raw = page.get_text("text").strip()
    if not raw:
        return ""
    return _rejoin_lines(raw)


def _pages_text(doc, start, end):
    """Extract text from page range [start, end) (0-indexed)."""
    parts = []
    for i in range(start, min(end, len(doc))):
        t = _page_text(doc, i)
        if t:
            parts.append(t)
    return "\n\n".join(parts)


def _normalize_ws(s):
    """Collapse whitespace, strip, replace special chars."""
    s = re.sub(r"[\u2018\u2019\u201c\u201d]", "'", s)
    s = re.sub(r"[\u2013\u2014\u2012]", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _titles_match(a, b):
    """Fuzzy title comparison, ignoring punctuation and case.

    PDF extraction can mangle ligatures (fi->?, fl->?) and special
    chars, so we use SequenceMatcher for approximate matching.
    """
    def _alpha(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())
    na, nb = _alpha(a), _alpha(b)
    if not na or not nb or len(na) < 4 or len(nb) < 4:
        return False
    # Exact substring match (fast path)
    if na in nb or nb in na:
        return True
    # Fuzzy match: handles ligature drops (fi->?, stripped to nothing)
    return SequenceMatcher(None, na, nb).ratio() >= 0.75


# ---------------------------------------------------------------------------
# PASS 1: Parse printed TOC pages
# ---------------------------------------------------------------------------

# Regex for TOC anchor line
_TOC_ANCHOR = re.compile(r"^\s*(TABLE\s+OF\s+)?CONTENTS\s*$", re.IGNORECASE)

# Regex patterns for TOC entry lines
_TOC_CHAPTER = re.compile(
    r"^\s*(?:chapter\s+)?(\d+)\s*[.:)_\-\s]+\s*(.+)",
    re.IGNORECASE,
)
_TOC_CHAPTER_WORD = re.compile(
    r"^\s*chapter\s+(\w+)\s*[.:)_\-\s]+\s*(.+)",
    re.IGNORECASE,
)
_TOC_PART = re.compile(
    r"^\s*part\s+(\d+|[IVXLCDM]+|\w+)\s*[.:)_\-\s]+\s*(.*)",
    re.IGNORECASE,
)

# Pattern for page numbers at end of line (after dots or spaces)
_PAGE_NUM_TAIL = re.compile(r"[\s.]+(\d{1,4})\s*$")


def _find_toc_pages(doc, max_scan=30):
    """Find the page range containing the printed TOC.

    Returns (start_page_0idx, end_page_0idx) or None.
    """
    for pg in range(min(max_scan, len(doc))):
        raw = doc[pg].get_text("text")
        lines = raw.strip().split("\n")
        for line in lines[:5]:  # TOC header is usually in first few lines
            if _TOC_ANCHOR.match(line.strip()):
                # Found TOC start. Determine how many pages the TOC spans.
                # Look for continuation pages using multiple signals:
                # trailing page numbers, standalone digit lines, numbered entries,
                # and TOC keyword lines (appendix, epilogue, etc.)
                end = pg + 1
                for candidate in range(pg + 1, min(pg + 8, len(doc))):
                    text = doc[candidate].get_text("text")
                    clines = [cl.strip() for cl in text.strip().split("\n") if cl.strip()]
                    if not clines:
                        break

                    toc_signals = 0
                    for cl in clines:
                        if _PAGE_NUM_TAIL.search(cl):
                            toc_signals += 1
                        elif cl.isdigit() and 1 <= int(cl) <= 999:
                            toc_signals += 1
                        elif re.match(r"^\d{1,3}\s*[.):]", cl):
                            toc_signals += 1
                        elif re.match(
                            r"^(chapter|part|appendix|introduction|preface|"
                            r"epilogue|conclusion|bibliography|acknowledgment|"
                            r"index|glossary|notes)\b",
                            cl, re.IGNORECASE,
                        ):
                            toc_signals += 1

                    # If >= 25% of non-empty lines are TOC indicators, it's a continuation
                    if toc_signals / len(clines) >= 0.25:
                        end = candidate + 1
                    else:
                        break
                return (pg, end)
    return None


def _parse_toc_text(toc_text):
    """Parse raw TOC text into structured entries.

    Returns list of dicts:
      {kind: "chapter"|"part"|"front_matter"|"back_matter",
       chapter_number: int|None, title: str, toc_page: int|None}
    """
    lines = toc_text.split("\n")
    entries = []

    i = 0
    while i < len(lines):
        line = _normalize_ws(lines[i])
        i += 1

        if not line:
            continue

        # Skip the "Contents" header itself
        if _TOC_ANCHOR.match(line):
            continue

        # Remove trailing page number
        page_num = None
        pm = _PAGE_NUM_TAIL.search(line)
        if pm:
            page_num = int(pm.group(1))
            line = line[:pm.start()].strip()

        # If line is JUST a number (page number on its own line from previous entry),
        # attach it to the previous entry if it has no page yet
        if line.isdigit() and entries and entries[-1]["toc_page"] is None:
            entries[-1]["toc_page"] = int(line)
            continue
        elif line.isdigit():
            # Standalone page number for a previous entry or orphaned
            # Try to attach to previous entry without page
            if entries and entries[-1]["toc_page"] is None:
                entries[-1]["toc_page"] = int(line)
            continue

        # If the line is empty after removing page number, skip
        if not line:
            continue

        # Remove dot leaders (......)
        line = re.sub(r"\.{3,}", " ", line)
        line = _normalize_ws(line)

        if not line:
            continue

        # Try to match patterns
        entry = None

        # PART entry
        pm_part = _TOC_PART.match(line)
        if pm_part:
            num_str = pm_part.group(1)
            title = pm_part.group(2).strip() if pm_part.group(2) else ""
            num = _parse_number(num_str)
            entry = {
                "kind": "part",
                "chapter_number": num,
                "title": f"Part {num_str}" + (f": {title}" if title else ""),
                "toc_page": page_num,
            }

        # CHAPTER entry (explicit "Chapter X" or numbered "X. Title")
        if not entry:
            # "Chapter 5 ... Title" or "Chapter Five ... Title"
            cm = re.match(
                r"^\s*chapter\s+(\d+|[IVXLCDM]+|\w+)\s*[.:)_\-\s]*\s*(.*)",
                line, re.IGNORECASE,
            )
            if cm:
                num_str = cm.group(1)
                title = cm.group(2).strip()
                num = _parse_number(num_str)
                # Remove leading/trailing special chars from title
                title = re.sub(r"^[^a-zA-Z0-9]+", "", title)
                entry = {
                    "kind": "chapter",
                    "chapter_number": num,
                    "title": title if title else f"Chapter {num_str}",
                    "toc_page": page_num,
                }

        # Numbered entry: "5. Title" or "5 Title"
        if not entry:
            nm = re.match(r"^\s*(\d{1,3})\s*[.):]\s+(.+)", line)
            if nm:
                num = int(nm.group(1))
                title = nm.group(2).strip()
                # If this entry has the same chapter number as the previous one,
                # it's a subtitle (e.g. "4. Dashboard..." then "4. GDP...").
                # Skip it to avoid duplicates.
                if entries and entries[-1].get("chapter_number") == num:
                    continue
                entry = {
                    "kind": "chapter",
                    "chapter_number": num,
                    "title": title,
                    "toc_page": page_num,
                }

        # Front matter
        if not entry:
            low = line.lower()
            for word in FRONT_MATTER_WORDS:
                if low == word or low.startswith(word + ":") or low.startswith(word + " "):
                    entry = {
                        "kind": "front_matter",
                        "chapter_number": None,
                        "title": line,
                        "toc_page": page_num,
                    }
                    break

        # Back matter
        if not entry:
            low = line.lower()
            for word in BACK_MATTER_WORDS:
                if low == word or low.startswith(word + ":") or low.startswith(word + " "):
                    entry = {
                        "kind": "back_matter",
                        "chapter_number": None,
                        "title": line,
                        "toc_page": page_num,
                    }
                    break

        # If we still didn't match, it might be a title-only line (no number).
        # Could be a subsection, appendix title, or continuation.
        if not entry and len(line) > 2:
            # Check if it looks like an appendix
            if re.match(r"appendix", line, re.IGNORECASE):
                entry = {
                    "kind": "back_matter",
                    "chapter_number": None,
                    "title": line,
                    "toc_page": page_num,
                }
            # If next line is just a page number, this is likely a real entry
            elif i < len(lines):
                next_line = lines[i].strip()
                if next_line.isdigit():
                    entry = {
                        "kind": "chapter",
                        "chapter_number": None,
                        "title": line,
                        "toc_page": int(next_line),
                    }
                    i += 1  # consume the page number line

        if entry:
            entries.append(entry)

    return entries


def _parse_printed_toc(doc):
    """PASS 1: Find and parse the printed TOC.

    Returns list of TOC entries or None if no TOC found.
    """
    toc_range = _find_toc_pages(doc)
    if not toc_range:
        return None

    start_pg, end_pg = toc_range
    _debug(f"[TOC] Found printed TOC on pages {start_pg+1}-{end_pg}")

    # Extract all text from TOC pages
    toc_text = ""
    for pg in range(start_pg, end_pg):
        toc_text += doc[pg].get_text("text") + "\n"

    entries = _parse_toc_text(toc_text)

    if len(entries) < 2:
        _debug("[TOC] Too few entries parsed from printed TOC")
        return None

    _debug(f"[TOC] Parsed {len(entries)} entries from printed TOC")
    for e in entries[:5]:
        _debug(f"  {e['kind']}: ch={e.get('chapter_number')} pg={e.get('toc_page')} title={e['title'][:50]}")
    if len(entries) > 5:
        _debug(f"  ... and {len(entries)-5} more")

    return entries


# ---------------------------------------------------------------------------
# PASS 2: Detect in-body heading boundaries via font-size analysis
# ---------------------------------------------------------------------------

def _detect_heading_boundaries(doc):
    """Scan all pages for heading-sized text that marks chapter/part starts.

    Returns list of dicts:
      {page: int (0-indexed), heading_text: str, font_size: float,
       chapter_number: int|None, kind: str|None}
    sorted by page number.
    """
    # First pass: collect all font sizes to find median body size
    all_sizes = []
    for page in doc:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    text = span.get("text", "").strip()
                    if text and size > 0 and len(text) > 2:
                        all_sizes.append(size)

    if not all_sizes:
        return []

    median_size = statistics.median(all_sizes)
    heading_threshold = median_size * 1.25  # headings are >= 1.25x body

    _debug(f"[Headings] Median font size: {median_size:.1f}, threshold: {heading_threshold:.1f}")

    # Second pass: find heading lines on each page
    boundaries = []
    seen_pages = set()  # one heading per page max

    for page_num in range(len(doc)):
        if page_num in seen_pages:
            continue

        page = doc[page_num]
        page_height = page.rect.height
        top_half = page_height * 0.5

        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        # Collect large-font lines in the top half of the page
        large_lines = []
        for block in blocks:
            if block.get("type") != 0:
                continue
            block_top = block.get("bbox", [0, 0, 0, 0])[1]
            if block_top > top_half:
                continue

            for line in block.get("lines", []):
                line_y = line["bbox"][1]
                if line_y > top_half:
                    continue

                parts = []
                max_size = 0
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    size = span.get("size", 0)
                    if text:
                        parts.append(text)
                        max_size = max(max_size, size)

                line_text = " ".join(parts).strip()
                if not line_text or max_size < heading_threshold:
                    continue

                large_lines.append({
                    "text": line_text,
                    "size": max_size,
                    "y": line_y,
                })

        if not large_lines:
            continue

        # Sort by y position (top to bottom)
        large_lines.sort(key=lambda x: x["y"])

        # Check if the top large line looks like a chapter/part marker
        heading_text = ""
        chapter_number = None
        kind = None

        for ll in large_lines:
            text = _normalize_ws(ll["text"])

            # "CHAPTER 5" or "Chapter 5"
            cm = re.match(
                r"^(?:CHAPTER|chapter|Chapter)\s+(\d+|[IVXLCDM]+|\w+)\s*$",
                text,
            )
            if cm:
                num = _parse_number(cm.group(1))
                if num is not None:
                    chapter_number = num
                    kind = "chapter"
                    # Title is likely the next large line
                    idx = large_lines.index(ll)
                    if idx + 1 < len(large_lines):
                        heading_text = _normalize_ws(large_lines[idx + 1]["text"])
                    else:
                        heading_text = f"Chapter {num}"
                    break

            # "PART ONE" or "PART 1" or "PART I"
            pm = re.match(
                r"^(?:PART|part|Part)\s+(\d+|[IVXLCDM]+|\w+)\s*$",
                text,
            )
            if pm:
                num = _parse_number(pm.group(1))
                kind = "part"
                chapter_number = num
                # Title is next large line
                idx = large_lines.index(ll)
                if idx + 1 < len(large_lines):
                    heading_text = _normalize_ws(large_lines[idx + 1]["text"])
                else:
                    heading_text = text
                break

            # Front matter headings (INTRODUCTION, PREFACE, etc.)
            low = text.lower()
            for word in FRONT_MATTER_WORDS:
                if low == word or low.startswith(word + ":"):
                    kind = "front_matter"
                    heading_text = text
                    break
            if kind:
                break

            # Back matter
            for word in BACK_MATTER_WORDS:
                if low == word or low.startswith(word + ":"):
                    kind = "back_matter"
                    heading_text = text
                    break
            if kind:
                break

            # Generic large heading — might be a chapter title without "Chapter X"
            # Only accept if it's significantly larger than body text
            if ll["size"] >= median_size * 1.4 and len(text) > 2 and len(text) < 80:
                kind = "unknown"
                heading_text = text
                break

        if kind:
            seen_pages.add(page_num)
            boundaries.append({
                "page": page_num,
                "heading_text": heading_text,
                "font_size": large_lines[0]["size"] if large_lines else 0,
                "chapter_number": chapter_number,
                "kind": kind,
            })

    _debug(f"[Headings] Detected {len(boundaries)} heading boundaries")
    for b in boundaries[:8]:
        _debug(f"  pg={b['page']+1} kind={b['kind']} ch={b['chapter_number']} text={b['heading_text'][:50]}")
    if len(boundaries) > 8:
        _debug(f"  ... and {len(boundaries)-8} more")

    return boundaries


# ---------------------------------------------------------------------------
# PASS 3: Align TOC entries to heading boundaries
# ---------------------------------------------------------------------------

def _align_toc_to_boundaries(toc_entries, boundaries, doc):
    """Align parsed TOC entries to detected heading boundaries.

    First calibrates the page offset between printed page numbers
    (used in the TOC) and actual PDF page numbers.  Then aligns each
    TOC entry to the nearest heading boundary using:
      1. Chapter-number matching (highest priority)
      2. Calibrated-page proximity (tight +/- 3 window)
      3. Title similarity matching (fallback)

    Returns list of chapter dicts ready for output.
    """
    total_pages = len(doc)

    # ------------------------------------------------------------------
    # Step 1: Calibrate page offset.
    # Many books number printed pages starting after front matter,
    # so printed "page 7" might be PDF page 10 (offset = +3).
    # ------------------------------------------------------------------
    offsets = []
    for entry in toc_entries:
        if entry.get("toc_page") is None or entry.get("chapter_number") is None:
            continue
        for b in boundaries:
            if b.get("chapter_number") == entry["chapter_number"] and b["kind"] == "chapter":
                offset = b["page"] - (entry["toc_page"] - 1)
                offsets.append(offset)
                break

    # Also try matching front-matter entries for calibration
    if not offsets:
        for entry in toc_entries:
            if entry.get("toc_page") is None or entry["kind"] != "front_matter":
                continue
            entry_low = entry["title"].lower()
            for b in boundaries:
                if b["kind"] == "front_matter":
                    b_low = b.get("heading_text", "").lower()
                    if b_low and (b_low in entry_low or entry_low in b_low):
                        offset = b["page"] - (entry["toc_page"] - 1)
                        offsets.append(offset)
                        break

    if offsets:
        page_offset = int(statistics.median(offsets))
    else:
        page_offset = 0

    _debug(f"[Align] Calibrated page offset: {page_offset}")

    # ------------------------------------------------------------------
    # Step 2: Align entries to boundaries.
    # ------------------------------------------------------------------
    used_boundaries = set()  # track boundary pages already claimed
    aligned = []

    for entry in toc_entries:
        if entry["kind"] == "part":
            continue  # structural dividers, not content chapters

        toc_page = entry.get("toc_page")
        ch_num = entry.get("chapter_number")
        best_boundary = None

        # Strategy 1: match by chapter number (highest priority)
        if ch_num is not None:
            candidates = [
                b for b in boundaries
                if b.get("chapter_number") == ch_num and b["page"] not in used_boundaries
            ]
            if candidates:
                if toc_page is not None:
                    expected = (toc_page - 1) + page_offset
                    candidates.sort(key=lambda b: abs(b["page"] - expected))
                best_boundary = candidates[0]

        # Strategy 2: match by calibrated page proximity
        if best_boundary is None and toc_page is not None:
            expected = (toc_page - 1) + page_offset
            candidates = [
                (b, abs(b["page"] - expected))
                for b in boundaries
                if b["page"] not in used_boundaries and abs(b["page"] - expected) <= 3
            ]
            if candidates:
                candidates.sort(key=lambda x: x[1])
                best_boundary = candidates[0][0]

        # Strategy 3: title similarity (fuzzy, handles ? vs - etc.)
        if best_boundary is None:
            for b in boundaries:
                if b["page"] not in used_boundaries:
                    b_text = b.get("heading_text", "")
                    if b_text and _titles_match(entry["title"], b_text):
                        best_boundary = b
                        break

        # Build aligned record
        if best_boundary:
            start_page = best_boundary["page"]
            used_boundaries.add(start_page)
            final_ch_num = ch_num if ch_num is not None else best_boundary.get("chapter_number")
            kind = entry["kind"]
            if best_boundary["kind"] in ("front_matter", "back_matter") and kind == "chapter":
                kind = best_boundary["kind"]
        elif toc_page is not None:
            start_page = max(0, (toc_page - 1) + page_offset)
            final_ch_num = ch_num
            kind = entry["kind"]
        else:
            continue  # cannot locate

        rec = {
            "start_page": start_page,
            "chapter_number": final_ch_num,
            "kind": kind,
            "title": entry["title"],
        }
        aligned.append(rec)

    # ------------------------------------------------------------------
    # Step 3: Build chapters from aligned page ranges.
    # ------------------------------------------------------------------
    aligned.sort(key=lambda x: x["start_page"])

    # Deduplicate (same start page keeps first)
    deduped = []
    for item in aligned:
        if not deduped or item["start_page"] != deduped[-1]["start_page"]:
            deduped.append(item)
    aligned = deduped

    chapters = []
    for i, item in enumerate(aligned):
        start = item["start_page"]
        end = aligned[i + 1]["start_page"] if i + 1 < len(aligned) else total_pages

        text = _pages_text(doc, start, end)
        wc = len(text.split())

        if wc < 30:
            continue

        ch = {
            "index": len(chapters),
            "section_type": item["kind"],
            "chapter_number": item["chapter_number"],
            "title": item["title"],
            "text": text,
            "page_start": start + 1,
            "page_end": end,
            "word_count": wc,
        }
        chapters.append(ch)

    return chapters


# ---------------------------------------------------------------------------
# Fallback: PDF outline (metadata TOC)
# ---------------------------------------------------------------------------

def _extract_via_outline(doc, boundaries):
    """Use PDF outline metadata, enhanced with heading boundary detection."""
    toc = doc.get_toc()
    if not toc:
        return None

    # Use the deepest level that has actual content chapters
    # Many books: L1=top sections, L2=parts, L3=chapters
    levels = set(level for level, _, _ in toc)
    max_level = max(levels)

    # Try each level from deepest to shallowest and pick the one
    # that has the most entries with "Chapter" in the title or
    # the most entries overall with reasonable page ranges
    best_entries = None
    best_level = None

    for try_level in sorted(levels, reverse=True):
        entries = [(title, page_num) for level, title, page_num in toc if level <= try_level]
        # Flatten: if filtering to a max level, keep all entries at or below
        if len(entries) >= 3:
            if best_entries is None or len(entries) > len(best_entries):
                best_entries = entries
                best_level = try_level

    if not best_entries or len(best_entries) < 2:
        return None

    _debug(f"[Outline] Using {len(best_entries)} entries (level <= {best_level})")

    chapters = []
    for i, (title, page_num) in enumerate(best_entries):
        start = max(0, page_num - 1)

        if i + 1 < len(best_entries):
            end = best_entries[i + 1][1] - 1
        else:
            end = len(doc)

        text = _pages_text(doc, start, end)
        wc = len(text.split())

        if wc < 30:
            continue

        # Determine section type and chapter number
        title_clean = _normalize_ws(title)
        section_type = "chapter"
        ch_num = None

        # Check if it's a Part
        pm = re.match(r"^part\s+(\d+|[IVXLCDM]+|\w+)", title_clean, re.IGNORECASE)
        if pm:
            section_type = "part"
            ch_num = _parse_number(pm.group(1))

        # Check if it's a Chapter with number
        cm = re.match(r"^chapter\s+(\d+|[IVXLCDM]+|\w+)", title_clean, re.IGNORECASE)
        if cm:
            ch_num = _parse_number(cm.group(1))
            section_type = "chapter"

        # Check front/back matter
        low = title_clean.lower()
        for word in FRONT_MATTER_WORDS:
            if low == word or low.startswith(word + ":") or low.startswith(word + " "):
                section_type = "front_matter"
                break
        for word in BACK_MATTER_WORDS:
            if low == word or low.startswith(word + ":") or low.startswith(word + " "):
                section_type = "back_matter"
                break

        # Try to get chapter number from boundary detection
        if ch_num is None and section_type == "chapter":
            for b in boundaries:
                if abs(b["page"] - start) <= 2 and b.get("chapter_number"):
                    ch_num = b["chapter_number"]
                    break

        chapters.append({
            "index": len(chapters),
            "section_type": section_type,
            "chapter_number": ch_num,
            "title": title_clean,
            "text": text,
            "page_start": start + 1,
            "page_end": min(end, len(doc)),
            "word_count": wc,
        })

    # Filter very short entries
    chapters = [c for c in chapters if c["word_count"] >= 50]

    if len(chapters) < 2:
        return None

    # Re-index
    for i, ch in enumerate(chapters):
        ch["index"] = i

    return chapters


# ---------------------------------------------------------------------------
# Fallback: heading-only detection (no TOC)
# ---------------------------------------------------------------------------

def _extract_via_headings_only(doc, boundaries):
    """Build chapters using only detected heading boundaries."""
    if len(boundaries) < 2:
        return None

    # Filter to significant boundaries (chapter/front_matter/back_matter/unknown)
    sig = [b for b in boundaries if b["kind"] != "part"]
    if len(sig) < 2:
        return None

    chapters = []
    for i, b in enumerate(sig):
        start = b["page"]
        if i + 1 < len(sig):
            end = sig[i + 1]["page"]
        else:
            end = len(doc)

        text = _pages_text(doc, start, end)
        wc = len(text.split())

        if wc < MIN_WORDS_PER_CHAPTER:
            continue

        chapters.append({
            "index": len(chapters),
            "section_type": b["kind"] if b["kind"] != "unknown" else "chapter",
            "chapter_number": b.get("chapter_number"),
            "title": b["heading_text"],
            "text": text,
            "page_start": start + 1,
            "page_end": min(end, len(doc)),
            "word_count": wc,
        })

    if len(chapters) < 2:
        return None

    for i, ch in enumerate(chapters):
        ch["index"] = i

    return chapters


# ---------------------------------------------------------------------------
# Fallback: page chunking
# ---------------------------------------------------------------------------

def _extract_via_page_chunks(doc):
    """Last resort: split into ~20-page sections."""
    total = len(doc)
    chapters = []
    idx = 0
    start = 0

    while start < total:
        end = min(start + PAGE_CHUNK_SIZE, total)
        text = _pages_text(doc, start, end)
        wc = len(text.split())

        chapters.append({
            "index": idx,
            "section_type": "chapter",
            "chapter_number": None,
            "title": f"Section {idx + 1} (Pages {start + 1}-{end})",
            "text": text,
            "page_start": start + 1,
            "page_end": end,
            "word_count": wc,
        })

        idx += 1
        start = end

    return chapters


# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------

def _assign_labels(chapters):
    """Assign chapter_label to each chapter based on section_type and chapter_number.

    Only numbered chapters get a label ("Ch. 1", "Ch. 2", etc.).
    Everything else (front matter, back matter, parts, unnumbered sections)
    gets an empty label so no badge is shown in the UI.
    """
    for ch in chapters:
        st = ch["section_type"]
        num = ch["chapter_number"]

        if st == "chapter" and num is not None:
            ch["chapter_label"] = f"Ch. {num}"
        else:
            ch["chapter_label"] = ""
            # Normalize unknown sections
            if st == "unknown":
                ch["section_type"] = "chapter"


# ---------------------------------------------------------------------------
# Main PDF entry point
# ---------------------------------------------------------------------------

def extract_chapters_pdf(filepath):
    """Extract chapters from a PDF using multi-pass strategy.

    Returns (chapters, detection_method).
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

    try:
        _debug(f"[PDF] Analyzing {doc.page_count}-page PDF: {os.path.basename(filepath)}")

        # PASS 2: Always detect heading boundaries (needed by multiple paths)
        boundaries = _detect_heading_boundaries(doc)

        # PASS 1: Try printed TOC
        toc_entries = _parse_printed_toc(doc)

        if toc_entries and len(toc_entries) >= 3:
            # PASS 3: Align TOC to boundaries
            chapters = _align_toc_to_boundaries(toc_entries, boundaries, doc)
            if chapters and len(chapters) >= 2:
                _assign_labels(chapters)
                _debug(f"[PDF] Success via printed TOC alignment: {len(chapters)} chapters")
                return chapters, "toc"

        # Fallback: PDF outline metadata
        if doc.get_toc():
            chapters = _extract_via_outline(doc, boundaries)
            if chapters and len(chapters) >= 2:
                _assign_labels(chapters)
                _debug(f"[PDF] Success via outline metadata: {len(chapters)} chapters")
                return chapters, "toc"

        # Fallback: heading-only detection
        chapters = _extract_via_headings_only(doc, boundaries)
        if chapters and len(chapters) >= 2:
            _assign_labels(chapters)
            _debug(f"[PDF] Success via heading detection: {len(chapters)} chapters")
            return chapters, "headings"

        # Last resort: page chunking
        chapters = _extract_via_page_chunks(doc)
        _assign_labels(chapters)
        _debug(f"[PDF] Fallback to page chunking: {len(chapters)} sections")
        return chapters, "auto_sections"

    finally:
        doc.close()


# ---------------------------------------------------------------------------
# EPUB chapter detection
# ---------------------------------------------------------------------------

def extract_chapters_epub(filepath):
    """Extract chapters from an EPUB using spine items and TOC titles."""
    try:
        book = epub.read_epub(filepath, options={"ignore_ncx": True})
    except Exception as e:
        raise ValueError(f"Could not open EPUB: {e}")

    # Build href -> TOC title map
    toc_map = {}
    for toc_item in book.toc:
        if isinstance(toc_item, epub.Link):
            href = toc_item.href.split("#")[0]
            toc_map[href] = toc_item.title
        elif isinstance(toc_item, tuple) and len(toc_item) >= 1:
            section = toc_item[0]
            if isinstance(section, epub.Link):
                href = section.href.split("#")[0]
                toc_map[href] = section.title

    chapters = []
    idx = 0

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

        full_text = "\n\n".join(texts)
        wc = len(full_text.split())

        if wc < 50:
            continue

        # Determine title
        item_href = item.get_name()
        title = toc_map.get(item_href)

        if not title:
            title_tag = soup.find("title")
            if title_tag and title_tag.get_text(strip=True):
                title = title_tag.get_text(strip=True)

        if not title:
            for htag in ["h1", "h2"]:
                found = soup.find(htag)
                if found:
                    title = found.get_text(strip=True)
                    break

        if not title:
            title = f"Chapter {idx + 1}"

        # Determine section type and chapter number
        section_type = "chapter"
        ch_num = None

        title_clean = _normalize_ws(title)
        title_low = title_clean.lower()

        # Check for "Chapter X" in title or first text
        cm = re.match(r"chapter\s+(\d+|[IVXLCDM]+|\w+)", title_clean, re.IGNORECASE)
        if cm:
            ch_num = _parse_number(cm.group(1))

        # If no chapter number in title, check the first 500 chars of text
        if ch_num is None:
            cm2 = re.search(r"\bchapter\s+(\d+|[IVXLCDM]+)\b", full_text[:500], re.IGNORECASE)
            if cm2:
                ch_num = _parse_number(cm2.group(1))

        # Front/back matter
        for word in FRONT_MATTER_WORDS:
            if title_low == word or title_low.startswith(word + ":") or title_low.startswith(word + " "):
                section_type = "front_matter"
                break
        for word in BACK_MATTER_WORDS:
            if title_low == word or title_low.startswith(word + ":") or title_low.startswith(word + " "):
                section_type = "back_matter"
                break

        chapters.append({
            "index": idx,
            "section_type": section_type,
            "chapter_number": ch_num,
            "title": title_clean,
            "text": full_text,
            "page_start": None,
            "page_end": None,
            "word_count": wc,
        })
        idx += 1

    if not chapters:
        raise ValueError("EPUB contains no extractable chapters.")

    _assign_labels(chapters)
    return chapters, "epub_spine"
