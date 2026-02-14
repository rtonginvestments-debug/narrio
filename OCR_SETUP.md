# OCR Setup for Image-Based PDFs

The app now supports OCR (Optical Character Recognition) to extract text from image-based or scanned PDFs.

## Requirements

You need to install:
1. **Python packages**: `pytesseract` and `Pillow` (already in requirements.txt)
2. **Tesseract OCR engine**: The actual OCR software

## Installation

### Windows

1. **Download Tesseract installer:**
   - Go to: https://github.com/UB-Mannheim/tesseract/wiki
   - Download the latest installer (e.g., `tesseract-ocr-w64-setup-5.3.x.exe`)

2. **Install Tesseract:**
   - Run the installer
   - **Important:** During installation, note the installation path (default: `C:\Program Files\Tesseract-OCR`)
   - Make sure to check "Add to PATH" option if available

3. **Add Tesseract to PATH (if not done automatically):**
   - Right-click "This PC" → Properties → Advanced system settings
   - Click "Environment Variables"
   - Under "System variables", find "Path" and click "Edit"
   - Click "New" and add: `C:\Program Files\Tesseract-OCR`
   - Click OK on all dialogs

4. **Install Python packages:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Verify installation:**
   ```bash
   tesseract --version
   ```

   Should output something like:
   ```
   tesseract 5.3.x
   ```

### macOS

```bash
# Install Tesseract using Homebrew
brew install tesseract

# Install Python packages
pip install -r requirements.txt
```

### Linux (Ubuntu/Debian)

```bash
# Install Tesseract
sudo apt-get update
sudo apt-get install tesseract-ocr

# Install Python packages
pip install -r requirements.txt
```

## How It Works

1. **Normal PDFs**: Text is extracted directly (fast, existing behavior)
2. **Image-based PDFs**:
   - If a page has very little or no extractable text (< 50 characters)
   - The app automatically renders the page as an image at 300 DPI
   - Runs OCR using Tesseract to extract text
   - Processes the OCR'd text normally

## Notes

- **OCR is slower** than normal text extraction (typically 2-5 seconds per page)
- **Accuracy depends on image quality** - clear, high-resolution scans work best
- **Works with mixed PDFs** - some pages with text, some with images
- **Graceful fallback** - if Tesseract is not installed, image-based PDFs will fail with a helpful error message

## Testing

To test OCR functionality:
1. Create a PDF with scanned images or screenshots of text
2. Upload to Narrio
3. Check the server logs - you should see: `Used OCR for X of Y pages`
4. The conversion should proceed normally

## Troubleshooting

**"Tesseract not found" error:**
- Make sure Tesseract is installed
- Check that it's in your PATH: `tesseract --version`
- On Windows, you may need to restart your terminal/IDE after installation

**OCR produces gibberish:**
- Image quality may be too low
- Try using a higher resolution scan (300 DPI recommended)
- Make sure the text is clear and not too small

**OCR is too slow:**
- OCR takes 2-5 seconds per page - this is normal
- For large documents (100+ pages), consider using the original text-based PDF if possible
