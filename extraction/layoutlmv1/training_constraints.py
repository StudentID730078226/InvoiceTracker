"""Reusable GPU constraints, extracted from the existing PyTorch training loop.

This module is prepared for subsequent training-code refactoring. Historical
checkpoints and the currently running, hash-frozen study did not call it.
"""
import tourch
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingConstraints:
    """Settings and scaler consumed by a training loop, not inference settings."""

    device: object
    batch_size: int
    max_sequence_length: int
    autocast_dtype: object
    gradient_scaler: object

    @contextmanager
    def autocast(self):
        """Apply FP16 to the forward/loss calculation within this context."""
        import torch
        with torch.autocast(device_type=self.device.type, dtype=self.autocast_dtype):
            yield

    def make_batch(self, window):
        """Build one GPU window batch and enforce its size and sequence limit."""
        import torch
        keys = ("input_ids", "attention_mask", "token_type_ids", "bbox", "labels")
        length = len(window["input_ids"])
        if not 0 < length <= self.max_sequence_length:
            raise ValueError("Training window must contain between 1 and 512 tokens.")
        if any(len(window[key]) != length for key in keys):
            raise ValueError("Tokens, masks, boxes and labels must have matching lengths.")
        return {
            key: torch.tensor([window[key]], dtype=torch.long, device=self.device)
            for key in keys
        }


def configure_training_constraints():
    """Configure the existing 4-GB-GPU training constraints in one place.

    Require CUDA, use one window per batch, cap inputs at 512 tokens, and
    provide FP16 autocast and gradient scaling. The caller must move the model
    to device, use these limits when tokenising/batching, and use the supplied
    autocast context and scaler in its training step. Returning settings alone
    does not resize inputs, move a model or start training.
    """

    # Require NVIDIA GPU execution; do not silently run the experiment on CPU.
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training configuration.")
    device = torch.device("cuda")

    # Process one token window per step to limit the GPU activation memory.
    batch_size = 1

    # Bound each sequence to LayoutLM v1's 512-token context, including specials.
    max_sequence_length = 512

    # Use this dtype inside autocast to reduce forward-pass memory requirements.
    autocast_dtype = torch.float16

    # Scale FP16 gradients to reduce underflow, then unscale before clipping.
    gradient_scaler = torch.amp.GradScaler("cuda")

    return TrainingConstraints(
        device=device,
        batch_size=batch_size,
        max_sequence_length=max_sequence_length,
        autocast_dtype=autocast_dtype,
        gradient_scaler=gradient_scaler,
    )
