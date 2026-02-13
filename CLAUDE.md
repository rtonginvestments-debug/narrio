# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PDF/EPUB to Audiobook — a Flask web app that converts uploaded PDF or EPUB files into MP3 audiobooks using Microsoft Edge's natural TTS voices via the `edge-tts` library.

## Tech Stack

- **Backend**: Python 3 + Flask
- **TTS**: `edge-tts` (Microsoft Edge natural voices, outputs MP3)
- **PDF extraction**: PyMuPDF (`fitz`)
- **EPUB extraction**: `ebooklib` + BeautifulSoup4
- **Frontend**: Vanilla HTML/CSS/JS
- **Progress**: Server-Sent Events (SSE)

## Running

```bash
pip install -r requirements.txt
python app.py
# Opens at http://localhost:5000
```

## File Structure

- `app.py` — Flask routes, background job management, SSE progress streaming
- `config.py` — Constants (upload limits, folders, defaults)
- `extractors/` — Text extraction from PDF (`pdf_extractor.py`) and EPUB (`epub_extractor.py`)
- `tts/engine.py` — edge-tts wrapper with streaming progress
- `templates/index.html` — Single-page frontend
- `static/css/style.css` — Dark theme UI styles
- `static/js/app.js` — Upload, SSE progress, download logic

## API Routes

- `GET /` — Main page
- `GET /api/voices` — List available English voices
- `POST /api/convert` — Upload file + start conversion (returns job ID)
- `GET /api/progress/<job_id>` — SSE stream of progress
- `GET /api/download/<job_id>` — Download completed MP3
