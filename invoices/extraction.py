"""Review-only LayoutLM v1 extraction integration."""
import logging
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .currency import infer_currency
from .forms import InvoiceForm
from .models import ExtractionRun, PendingUpload
from .services import event, locked_invoice

log = logging.getLogger(__name__)
FIELDS = {"supplier", "invoice_number", "invoice_date", "due_date", "currency", "total"}
# CPU model/library cold starts can be substantial on the local Windows setup.
INFERENCE_TIMEOUT_SECONDS = 600


def normalize_suggestions(suggestions):
    normalized = {key: str(value).strip() for key, value in suggestions.items() if key in FIELDS and value not in (None, "")}
    for field in ("invoice_date", "due_date"):
        value = normalized.get(field)
        if not value:
            continue
        parsed = None
        for date_format in (
            "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y",
            "%d/%m/%Y", "%d/%m/%y", "%d-%b-%Y", "%d %B %Y",
            "%d %b %Y", "%b. %d, %Y", "%B %d, %Y", "%d-%B-%Y", "%d-%m-%Y", "%m-%d-%Y",
        ):
            try:
                parsed = datetime.strptime(value, date_format)
                break
            except ValueError:
                continue
        if parsed:
            normalized[field] = parsed.date().isoformat()

    total = normalized.get("total")
    if total:
        total = unicodedata.normalize('NFKC', total)
        currency = infer_currency([], total)
        if "currency" not in normalized and currency['currency']:
            normalized['currency'] = currency['currency']
        cleaned_total = re.sub(r"(?i)\b(?:GBP|EUR|USD)\b|[$£€]", "", total)
        cleaned_total = cleaned_total.replace(",", "").strip()
        try:
            normalized["total"] = str(Decimal(cleaned_total))
        except InvalidOperation:
            pass
    return normalized


def load_extraction_result(result_path):
    """Read inference JSON and return normalised, form-validated suggestions.

    Preserve warnings and model provenance alongside the cleaned fields.
    Invalid individual fields are omitted so users can enter them manually.
    This helper does not start inference or write to the database.
    """
    # Read the result produced by the local inference worker.
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))

    # Convert model date, amount and currency representations for Django forms.
    suggestions = normalize_suggestions(result.get("suggestions", {}))

    # Reuse application validation rather than accepting every model value.
    candidate = InvoiceForm({**suggestions, "notes": ""})
    candidate.is_valid()
    result["suggestions"] = {
        name: value for name, value in suggestions.items()
        if name not in candidate.errors
    }

    # Return cleaned fields with the original warnings and model version.
    return result


def review_form(invoice, run):
    initial = {
        name: run.suggestions[name]
        for name in FIELDS
        if getattr(invoice, name) in (None, "")
        and run.suggestions.get(name) not in (None, "")
    }
    form = InvoiceForm(instance=invoice, initial=initial)
    for name in form.fields:
        if name in initial:
            form.fields[name].help_text = "Suggested value. Check it against the invoice."
    return form


def _worker_python():
    configured = os.environ.get("INVOICE_EXTRACTION_PYTHON")
    return Path(configured) if configured else Path(settings.BASE_DIR) / ".venv-easyocr-gpu/Scripts/python.exe"


def launch_worker(run_id):
    worker = _worker_python()
    if not worker.is_file():
        raise RuntimeError(f"Extraction environment is unavailable: {worker}")
    log_dir = Path(settings.MEDIA_ROOT) / "extraction_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    output = (log_dir / f"{run_id}.log").open("ab")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}
    try:
        subprocess.Popen(
            [str(worker), str(settings.BASE_DIR / "manage.py"), "process_extraction", str(run_id)],
            cwd=settings.BASE_DIR, stdout=output, stderr=subprocess.STDOUT, **options,
        )
    finally:
        output.close()


def _launch_pending_worker(pending_id):
    worker = _worker_python()
    if not worker.is_file():
        raise RuntimeError(f"Extraction environment is unavailable: {worker}")
    log_dir = Path(settings.MEDIA_ROOT) / "extraction_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    output = (log_dir / f"pending-{pending_id}.log").open("ab")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}
    try:
        subprocess.Popen(
            [str(worker), str(settings.BASE_DIR / "manage.py"), "process_extraction",
             "--pending", str(pending_id)],
            cwd=settings.BASE_DIR, stdout=output, stderr=subprocess.STDOUT, **options,
        )
    finally:
        output.close()


@transaction.atomic
def start_pending_extraction(user, business_id, pk):
    pending = get_object_or_404(
        PendingUpload.objects.select_for_update(),
        pk=pk, business_id=business_id, uploaded_by=user,
    )
    if pending.status == "confirmed":
        raise ValidationError("This upload has already been confirmed.")
    if pending.status in ("queued", "running"):
        return pending
    worker = _worker_python()
    if not worker.is_file():
        raise RuntimeError(f"Extraction environment is unavailable: {worker}")
    pending.status = "queued"
    pending.error = ""
    pending.finished_at = None
    pending.save(update_fields=("status", "error", "finished_at"))
    transaction.on_commit(lambda: _launch_pending_worker(pending.pk))
    return pending


@transaction.atomic
def start_extraction(user, business_id, pk):
    invoice = locked_invoice(user, business_id, pk)
    if not invoice.editable:
        raise ValidationError("Only draft and returned invoices can be scanned.")
    cutoff = timezone.now() - timedelta(minutes=10)
    invoice.extractions.filter(status__in=("queued", "running"), created_at__lt=cutoff).update(
        status=ExtractionRun.Status.FAILED,
        error="The scan expired. Please retry.",
        finished_at=timezone.now(),
    )
    active = invoice.extractions.filter(status__in=("queued", "running")).first()
    if active:
        return active
    worker = _worker_python()
    if not worker.is_file():
        raise RuntimeError(f"Extraction environment is unavailable: {worker}")
    try:
        run = ExtractionRun.objects.create(
            invoice=invoice,
            requested_by=user,
            source_hash=invoice.file_hash,
            invoice_revision=invoice.updated_at,
            model_version="layoutlm-v1-1500-A-seed42-epoch10-evidence2",
        )
    except IntegrityError:
        return invoice.extractions.get(status__in=("queued", "running"))
    event(invoice, user, "extraction_requested", message=f"Combined model scan #{run.pk} started.")
    transaction.on_commit(lambda: launch_worker(run.pk))
    return run


def process_run(run_id):
    if ExtractionRun.objects.filter(pk=run_id, status=ExtractionRun.Status.QUEUED).update(
        status=ExtractionRun.Status.RUNNING
    ) != 1:
        return
    run = ExtractionRun.objects.select_related("invoice").get(pk=run_id)
    try:
        if not run.invoice.editable:
            raise ValueError("Invoice is no longer editable.")
        if run.invoice.file_hash != run.source_hash:
            raise ValueError("The source document changed. Scan it again.")
        result_path = Path(settings.MEDIA_ROOT) / "extraction_results" / f"{run.pk}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        worker = _worker_python()
        script = settings.BASE_DIR / "extraction/layoutlmv1/application_inference.py"
        subprocess.run(
            [str(worker), str(script), run.invoice.source_file.path, str(result_path)],
            cwd=settings.BASE_DIR, check=True, timeout=INFERENCE_TIMEOUT_SECONDS,
        )
        result = load_extraction_result(result_path)
        suggestions = result["suggestions"]
        updates = {
            "status": ExtractionRun.Status.SUCCEEDED,
            "suggestions": suggestions,
            "warnings": result.get("warnings", []),
            "model_version": result.get("model_version", run.model_version),
            "error": "",
            "finished_at": timezone.now(),
        }
    except Exception as exc:
        log.exception("Extraction failed for run %s", run_id)
        updates = {
            "status": ExtractionRun.Status.FAILED,
            "error": str(exc) if isinstance(exc, ValueError) else "The document could not be read.",
            "finished_at": timezone.now(),
        }
    ExtractionRun.objects.filter(pk=run_id, status=ExtractionRun.Status.RUNNING).update(**updates)


def process_pending_run(pending_id):
    if PendingUpload.objects.filter(pk=pending_id, status="queued").update(status="running") != 1:
        return
    pending = PendingUpload.objects.get(pk=pending_id)
    try:
        result_path = Path(settings.MEDIA_ROOT) / "extraction_results" / f"pending-{pending.pk}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        worker = _worker_python()
        script = settings.BASE_DIR / "extraction/layoutlmv1/application_inference.py"
        subprocess.run(
            [str(worker), str(script), pending.source_file.path, str(result_path)],
            cwd=settings.BASE_DIR, check=True, timeout=INFERENCE_TIMEOUT_SECONDS,
        )
        result = load_extraction_result(result_path)
        suggestions = result["suggestions"]
        PendingUpload.objects.filter(pk=pending.pk, status="running").update(
            status="succeeded", suggestions=suggestions, warnings=result.get("warnings", []),
            model_version=result.get("model_version", "layoutlm-v1-1500-A-seed42-epoch10-evidence2"),
            error="", finished_at=timezone.now(),
        )
    except Exception as exc:
        log.exception("Pending extraction failed for %s", pending_id)
        PendingUpload.objects.filter(pk=pending.pk, status="running").update(
            status="failed",
            error=str(exc) if isinstance(exc, ValueError) else "The document could not be read.",
            finished_at=timezone.now(),
        )


@transaction.atomic
def apply_suggestions(user, business_id, pk, run_id, data):
    invoice = locked_invoice(user, business_id, pk)
    run = get_object_or_404(ExtractionRun.objects.select_for_update(), pk=run_id, invoice=invoice)
    if not invoice.editable or run.status != ExtractionRun.Status.SUCCEEDED or run.applied_at:
        raise ValidationError("These suggestions are no longer available.")
    if invoice.updated_at != run.invoice_revision or invoice.file_hash != run.source_hash:
        raise ValidationError("Invoice details changed after the scan. Scan again.")
    selected = data.getlist("confirm_fields")
    if not selected or any(name not in run.suggestions for name in selected):
        raise ValidationError("Select at least one suggested field.")
    changes = {name: run.suggestions[name] for name in selected}
    form = InvoiceForm({**{f: getattr(invoice, f) for f in InvoiceForm.Meta.fields}, **changes}, instance=invoice)
    if not form.is_valid():
        return invoice, form
    for name in selected:
        setattr(invoice, name, form.cleaned_data[name])
    invoice.save(update_fields=[*selected, "updated_at"])
    run.applied_at = timezone.now()
    run.save(update_fields=("applied_at",))
    event(invoice, user, "extraction_confirmed", message=f"Combined model suggestions from scan #{run.pk} confirmed.")
    return invoice, form
