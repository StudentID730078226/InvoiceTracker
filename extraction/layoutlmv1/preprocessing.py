"""Document decoding; contrast enhancement is handled separately afterward."""
from pathlib import Path
from PIL import Image
from invoices.document_evidence import screenshot_page_bounds

def pages(source):
    """Yield RGB pages; image_extraction applies contrast after page decoding."""
    source=Path(source)
    if source.suffix.lower()=='.pdf':
        import pypdfium2 as pdfium
        pdf=pdfium.PdfDocument(str(source))
        try:
            for number in range(len(pdf)):
                # Rasterise PDFs at a fixed scale before text detection/recognition.
                yield pdf[number].render(scale=2).to_pil().convert('RGB'),number
        finally:pdf.close()
    else:
        with Image.open(source) as opened:image=opened.convert('RGB')
        # Split only pixel-evidenced screenshot gutters; never consult field labels.
        for number,bounds in enumerate(screenshot_page_bounds(image)):
            yield image.crop(bounds),number
