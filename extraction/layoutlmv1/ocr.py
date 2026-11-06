"""OCR text recognition, separated from LayoutLM field interpretation."""


def extract_text(image, predictor):
    """Read one page with docTR and return words, confidence and spatial boxes.

    The predictor detects text regions and recognises their content. It does
    not decide which value is the invoice number, date or total.
    """
    import numpy as np
    import torch

    # Supply RGB image pixels to OCR without recording training gradients.
    with torch.inference_mode():
        page = predictor([np.asarray(image.convert("RGB"))]).export()["pages"][0]

    # Keep docTR's block/line/word reading order for the field model.
    recognised_words = []
    for block in page["blocks"]:
        for line in block["lines"]:
            for word in line["words"]:
                if not word["value"].strip():
                    continue

                # Retain real detection coordinates, normalised to page dimensions.
                (left, top), (right, bottom) = word["geometry"]
                recognised_words.append({
                    "text": word["value"],
                    "bbox": [left, top, right, bottom],
                    "ocr_confidence": float(word["confidence"]),
                })
    return recognised_words
