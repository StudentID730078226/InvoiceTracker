"""Verified loading of the matching invoice tokenizer and trained field model."""
import hashlib
import json
from pathlib import Path

from transformers import AutoConfig, AutoTokenizer, LayoutLMForTokenClassification


def load_invoice_tokenizer(checkpoint):
    """Restore the tokenizer saved alongside the fine-tuned invoice model.

    Matching tokenisation keeps OCR words aligned with the model's subtokens.
    """
    # Read local tokenizer files; do not download a replacement vocabulary.
    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint, local_files_only=True, use_fast=True,
    )
    return tokenizer


def load_invoice_model(checkpoint, device="cpu"):
    """Restore the trained encoder and field head, ready for prediction.

    Load saved weights rather than rebuilding or training the architecture.
    The field model receives OCR words and boxes, not image pixels.
    """
    # Recover the saved encoder dimensions and invoice label definitions.
    configuration = AutoConfig.from_pretrained(checkpoint, local_files_only=True)

    # Load both trained components: the pretrained-derived encoder and field head.
    model = LayoutLMForTokenClassification.from_pretrained(
        checkpoint, config=configuration, local_files_only=True,
    ).to(device).eval()

    # Record actual model dimensions for JSON evidence and architecture screenshots.
    model.invoice_architecture = {
        "encoder": configuration.model_type,
        "encoder_layers": configuration.num_hidden_layers,
        "attention_heads": configuration.num_attention_heads,
        "hidden_dimensions": configuration.hidden_size,
        "classifier": type(model.classifier).__name__,
        "classifier_input": model.classifier.in_features,
        "classifier_output": model.classifier.out_features,
        "maximum_tokens": configuration.max_position_embeddings,
        "labels": configuration.id2label,
    }
    return model


def load_trained_model(checkpoint, device="cpu"):
    """Verify one checkpoint, then return its matching tokenizer and model."""
    checkpoint = Path(checkpoint)

    # Check every deployed file before either component is loaded.
    provenance = json.loads((Path(__file__).parent / "model_provenance.json").read_text())
    for name, expected_hash in provenance["files"].items():
        if hashlib.sha256((checkpoint / name).read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError("Model provenance mismatch: " + name)

    # Restore text preparation and trained field prediction from the same folder.
    tokenizer = load_invoice_tokenizer(checkpoint)
    model = load_invoice_model(checkpoint, device)

    # Preserve the return interface used by the extraction adapter.
    return tokenizer, model
