"""Readable configuration refactoring of the current six-configuration study.

Prepared for future integration: the running hash-frozen experiment still sets
these values directly in its own run.py. This module does not start training,
create directories, configure a Trainer, or change the active experiment.
"""
from pathlib import Path


def configure_training_arguments(output_root, configuration="R_reference", seed=42):
    """Return the tested hyperparameters, stopping policy and evidence paths.

    Each alternative changes one factor from the reference. A training loop
    must explicitly consume these values to apply them; returning this mapping
    alone does not modify an optimiser, tokenizer or logging behaviour.
    """
    # Learning and model context
    encoder_learning_rate = 1e-5       # Controls updates to the pretrained encoder.
    head_learning_rate = 5e-5          # Controls updates to the field-classification head.
    supplier_total_weight = 1.0        # Sets the loss contribution of supplier and total tokens.
    token_overlap = 64                # Retains shared context between adjacent token windows.

    # Training and validation
    maximum_epochs = 10               # Limits the number of passes through the training set.
    validation_every_epochs = 2       # Sets how often development performance is measured.
    early_stopping_checks = 3         # Limits validation checks without improvement.
    optimizer = "AdamW"                # Chooses the parameter-update algorithm.
    weight_decay = 0.01               # Regularises model weights during optimisation.
    maximum_gradient_norm = 1.0       # Limits gradient magnitude before an update.

    # Progress reporting and checkpoint selection
    log_first_step = True             # Records progress when a training epoch begins.
    log_every_steps = 25              # Sets the interval between live progress updates.
    selection_metric = "development mean core-field exact accuracy"  # Ranks checkpoints.

    # Output locations
    output_root = Path(output_root)    # Identifies the experiment output folder.
    run_directory = output_root / "runs" / configuration / str(seed)  # Isolates each fit.

    # Change only the factor named by the selected experimental configuration.
    if configuration == "A_high_rate":
        encoder_learning_rate, head_learning_rate = 2e-5, 1e-4
    elif configuration == "B_low_rate":
        encoder_learning_rate, head_learning_rate = 5e-6, 2.5e-5
    elif configuration == "C_weight_1_5":
        supplier_total_weight = 1.5
    elif configuration == "D_weight_2":
        supplier_total_weight = 2.0
    elif configuration == "E_overlap128":
        token_overlap = 128
    elif configuration != "R_reference":
        raise ValueError("Unknown training configuration.")

    # Use the two recorded seeds for matched configuration comparisons.
    if seed not in (42, 43):
        raise ValueError("This study uses seeds 42 and 43.")

    # Return settings and paths; the caller controls execution and file writes.
    return {
        "configuration": configuration,
        "seed": seed,
        "encoder_learning_rate": encoder_learning_rate,
        "head_learning_rate": head_learning_rate,
        "supplier_total_weight": supplier_total_weight,
        "token_overlap": token_overlap,
        "optimizer": optimizer,
        "weight_decay": weight_decay,
        "maximum_gradient_norm": maximum_gradient_norm,
        "maximum_epochs": maximum_epochs,
        "validation_every_epochs": validation_every_epochs,
        "early_stopping_checks": early_stopping_checks,
        "log_first_step": log_first_step,
        "log_every_steps": log_every_steps,
        "selection_metric": selection_metric,
        "progress_file": output_root / "progress.json",
        "epoch_metrics_file": run_directory / "epoch_metrics.json",
        "summary_file": run_directory / "summary.json",
        "checkpoint_directory": run_directory / "best_checkpoint",
    }


def configure_comparison_study(output_root):
    """Describe all twelve fits in the actual reference-last execution order."""
    # Keep each alternative fixed beforehand; do not adapt it using test scores.
    configurations = (
        "A_high_rate", "B_low_rate", "C_weight_1_5",
        "D_weight_2", "E_overlap128", "R_reference",
    )
    return [
        configure_training_arguments(output_root, configuration, seed)
        for configuration in configurations
        for seed in (42, 43)
    ]
