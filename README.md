# Business invoice application

Upload an invoice image or PDF, then request editable extraction suggestions on the confirmation page. The application now runs **LayoutLM v1** through [the active inference module](ml/layoutlmv1/README.md). Correct or replace the suggestions and explicitly confirm before saving a draft. Manual entry remains available.

The selected checkpoint is `models/layoutlm-v1-invoice`: configuration A_baseline, seed 42, epoch 10 from the completed 1500-document study. Provenance is recorded in `ml/layoutlmv1/model_provenance.json`. The augmented1650 experiment is separate and is not automatically promoted.

Local `.venv-easyocr-gpu` supplies docTR OCR; default OCR compares CRNN and PARSeq per page. `INVOICE_OCR_ARM=crnn` or `parseq` forces an arm. Application field-model inference defaults to the local CUDA GPU; OCR remains on CPU. `INVOICE_MODEL_DEVICE=cpu` selects CPU inference. Requested CUDA fails explicitly if unavailable or less than 1 GiB of GPU memory is free. `INVOICE_EXTRACTION_PYTHON` overrides the worker interpreter. Suggestions are staged for human review, not silently written into confirmed invoice fields.

The previous v3 application adapter and checkpoint are preserved in `lvm 3/`. Historical experiments remain at their original paths to preserve provenance and running-study dependencies.

Incoming app pages now use lightness-channel CLAHE in `ml/layoutlmv1/image_enhancement.py` before OCR. Set `INVOICE_CONTRAST=none` for an unenhanced control. The model weights and frozen experiment inputs are unchanged; historical benchmark scores do not establish the accuracy of this newer pixel policy.

## Run locally

```powershell
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000 --insecure
```

Install application dependencies from `requirements.txt` when setting up a new environment.

## Application tests

```powershell
.venv/Scripts/python.exe manage.py test accounts invoices
```

Current code lives in `accounts/`, `invoices/`, `templates/` and `static/`. Application tests are grouped under each application's `tests/` directory.

Archiving previous ML material is **paused and partial**. Material already moved, including source datasets, is preserved under `archive/ml_fresh_start_2026-10-30/`. They are not used by the application. Earlier archives also remain under `archive/`.

Active inference is documented in [ml/layoutlmv1/README.md](ml/layoutlmv1/README.md). The LayoutLMv3 README describes historical research. Database diagrams remain under `reports/current/database_diagrams/`.

The consolidated model-selection history is documented in
[ml_evaluation/training_selection_process/MODEL_SELECTION_PROCESS.md](ml_evaluation/training_selection_process/MODEL_SELECTION_PROCESS.md).
## Workspace roles

Memberships can use the current `employee` and `admin` roles. Employees can upload invoices, review extraction suggestions, and view only their own submissions. Administrators retain the full workspace dashboard, expenditure view, invoice review queue, approval/return actions, and export access. Existing `client` and `accountant` memberships remain supported for compatibility with earlier local data.

Administrators can add users from **Organisation users** in the workspace navigation. The local exemplar can be created with:

```powershell
.venv/Scripts/python.exe manage.py create_exemplar_org
```

This creates `Exemplar Organisation` with `exemplar_admin` and `exemplar_employee`. Both use the local development password `ExemplarInvoice-2026!`; change it before using outside local development.

Administrators can remove other members from the same page. An administrator cannot remove their own access, and the final administrator cannot be removed. Submitted invoices are reviewed from **Review queue**; an administrator can approve or return/deny an invoice with a required comment, after which the employee can edit and resubmit it.
