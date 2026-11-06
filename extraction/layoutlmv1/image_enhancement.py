"""Pixel-only contrast enhancement for incoming invoice pages."""
import os
import cv2
import numpy as np
from PIL import Image

CLAHE_CLIP_LIMIT = 1.5
CLAHE_TILE_GRID = (8, 8)


def enhance_contrast(image):
    """Improve local contrast with OpenCV CLAHE while preserving page geometry.

    Enhance the LAB lightness channel rather than each RGB channel, retaining
    colour information. No rotation, cropping or resizing changes word boxes.
    INVOICE_CONTRAST=none provides a controlled unenhanced comparison path.
    """
    
    # Reject unsupported inputs before passing pixel data to OpenCV.
    if not isinstance(image, Image.Image):
        raise TypeError("Contrast enhancement expects a PIL image.")

    # Convert consistently to RGB without changing the original image object.
    rgb_image = image.convert("RGB")
    profile = os.environ.get("INVOICE_CONTRAST", "clahe").lower()
    if profile == "none":
        return rgb_image
    if profile != "clahe":
        raise ValueError("INVOICE_CONTRAST must be clahe or none.")

    # Separate brightness from colour before adjusting local contrast.
    lab_pixels = cv2.cvtColor(np.asarray(rgb_image), cv2.COLOR_RGB2LAB)

    # Limit local amplification to avoid excessive enhancement of noise.
    contrast_filter = cv2.createCLAHE(
        clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID,
    )

    # Enhance only lightness, preserving the two colour channels.
    lab_pixels[:, :, 0] = contrast_filter.apply(lab_pixels[:, :, 0])

    # Return a new RGB page with the same dimensions for subsequent OCR.
    enhanced_pixels = cv2.cvtColor(lab_pixels, cv2.COLOR_LAB2RGB)
    return Image.fromarray(enhanced_pixels)


def contrast_settings():
    """Describe the pixel policy used for the current extraction request."""
    return {"contrast": os.environ.get("INVOICE_CONTRAST", "clahe").lower(),
            "clip_limit": CLAHE_CLIP_LIMIT, "tile_grid": list(CLAHE_TILE_GRID),
            "geometry_changed": False}
