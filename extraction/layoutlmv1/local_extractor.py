"""Image-level adapter for the real OCR plus LayoutLM v1 pipeline."""
from pathlib import Path
from threading import Lock
import os


class LocalInvoiceExtractor:
    """Expose extract(image) without claiming it is a native LayoutLM method."""

    def __init__(self, checkpoint):
        self.checkpoint = Path(checkpoint)
        if not self.checkpoint.is_dir():
            raise FileNotFoundError("The local invoice checkpoint is unavailable.")
        self._ready = False
        self._load_lock = Lock()

    @classmethod
    def load_local(cls, checkpoint):
        """Create a local checkpoint adapter; defer weight loading until needed."""
        return cls(checkpoint)

    def _initialise(self):
        """Load verified field weights and CPU OCR once per worker process."""
        if self._ready:return
        with self._load_lock:
            if self._ready:return
            import torch
            from doctr.models import ocr_predictor
            from extraction.layoutlmv1.field_model import load_trained_model
            torch.set_num_threads(2)
            self.device = os.environ.get("INVOICE_MODEL_DEVICE", "cuda").lower()
            if self.device not in {"cpu", "cuda"}:
                raise ValueError("INVOICE_MODEL_DEVICE must be cpu or cuda")
            if self.device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but unavailable")
            if self.device == "cuda" and torch.cuda.mem_get_info()[0] < 1024**3:
                raise RuntimeError("The GPU is busy. Retry extraction when more memory is available.")
            self.arm = os.environ.get("INVOICE_OCR_ARM", "combined").lower()
            if self.arm not in {"combined", "crnn", "parseq"}:
                raise ValueError("INVOICE_OCR_ARM must be combined, crnn or parseq")
            self.tokenizer, self.model = load_trained_model(self.checkpoint, self.device)
            names = ["crnn", "parseq"] if self.arm == "combined" else [self.arm]
            self.predictors = {
                name: ocr_predictor(
                    det_arch="db_resnet50",
                    reco_arch="crnn_vgg16_bn" if name == "crnn" else "parseq",
                    pretrained=True, assume_straight_pages=True, det_bs=1, reco_bs=16,
                ).to("cpu").eval() for name in names
            }
            self._ready = True

    def extract(self, image):
        """Read one RGB page, classify words and return suggestions plus evidence.

        No annotations are accepted. LayoutLM v1 sees OCR words/positions;
        the image pixels are supplied to OCR, not to the field model.
        """
        from PIL import Image
        from extraction.layoutlmv1.application_inference import finish, MODEL_VERSION
        from extraction.layoutlmv1.ocr import extract_text
        from extraction.layoutlmv1.runtime import predict_page, select_fields
        from invoices.document_evidence import retry_number_words
        if not isinstance(image, Image.Image):
            raise TypeError("extract_image expects a PIL image; file decoding is separate.")
        self._initialise()
        image = image.convert("RGB")
        alternatives = []
        for name, predictor in self.predictors.items():
            words = extract_text(image, predictor)
            words, retry = retry_number_words(image, words, lambda crop: extract_text(crop, predictor))
            spans, tokens = predict_page(words, self.tokenizer, self.model, self.device)
            alternatives.append((sum(s["score"] for s in spans), name, words, spans, tokens, retry))
        _, chosen, words, spans, tokens, retry = max(alternatives, key=lambda a: a[0])
        page_words = [{"text": w["text"], "bbox_normalized": w["bbox"]} for w in words]
        raw = select_fields(spans)
        selected, warnings, evidence = finish(raw, [{"page": 0, "words": page_words}], words)
        return {
            "suggestions": selected, "raw_model_suggestions": raw,
            "warnings": warnings, "model_version": MODEL_VERSION, "evidence": evidence,
            "model_architecture": self.model.invoice_architecture,
            "page_state": {"words": words, "spans": spans, "tokens": tokens,
                           "ocr_arm": chosen, "number_retry": retry,
                           "image_size": image.size},
        }
