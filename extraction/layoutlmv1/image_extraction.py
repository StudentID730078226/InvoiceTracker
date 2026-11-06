"""Small application entry point; OCR and field prediction live in the adapter."""
from pathlib import Path
from ml.layoutlmv1.local_extractor import LocalInvoiceExtractor
from ml.layoutlmv1.image_enhancement import enhance_contrast


def preprocess_image(image):
    """Apply the separate CLAHE contrast stage before OCR reads the page."""
    return enhance_contrast(image)


# Configure the trained checkpoint; weights load lazily on the first extraction.
lvm_model = LocalInvoiceExtractor.load_local(
    Path(__file__).resolve().parents[2] / "models/layoutlm-v1-invoice"
)


def extract_image(image):
    """Receive invoice images and return their extracted fields and evidence."""
    image = preprocess_image(image)                    # Enhance local contrast for OCR.
    extracted_information = lvm_model.extract(image)   # Run local OCR and LayoutLM v1.
    return extracted_information                      # Return extracted values to the user.
