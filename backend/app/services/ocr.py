"""OCR service using Tesseract if available."""
import io

try:  # pragma: no cover - optional dependency
    import pytesseract
    from PIL import Image
except Exception:  # pragma: no cover
    pytesseract = None
    Image = None


def extract_text(image_bytes: bytes) -> str:
    """Extract text from an image using Tesseract if installed."""
    if pytesseract and Image:  # pragma: no branch
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image)
    return ""
