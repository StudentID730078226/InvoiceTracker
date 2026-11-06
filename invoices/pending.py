"""Temporary upload -> manual entry -> explicit confirmation -> saved invoice."""
from datetime import timedelta
import hashlib
from pathlib import Path
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.services import accessible_business
from .models import PendingUpload, Invoice
from .forms import ConfirmInvoiceForm
from .services import validate_document, DuplicateDocument, event


def expire_uploads():
    for upload in PendingUpload.objects.filter(created_at__lt=timezone.now()-timedelta(hours=24)):
        discard_upload(upload)


@transaction.atomic
def discard_upload(upload):
    upload = PendingUpload.objects.select_for_update().filter(pk=upload.pk).first()
    if upload is None:
        return
    storage, name = upload.source_file.storage, upload.source_file.name
    upload.delete()
    if name:
        transaction.on_commit(lambda: storage.delete(name))


def stage_upload(user, business_id, source):
    business = accessible_business(user, business_id)
    expire_uploads()
    digest, content_type = validate_document(source)
    existing = Invoice.objects.filter(business=business, file_hash=digest).first()
    if existing:
        raise DuplicateDocument(existing)
    existing = PendingUpload.objects.filter(business=business, file_hash=digest).first()
    if existing and existing.status == 'confirmed':
        discard_upload(existing)
        existing = None
    if existing:
        if existing.uploaded_by_id != user.pk:
            raise ValidationError('This document is already awaiting confirmation in this business.')
        return existing
    upload = PendingUpload(business=business, uploaded_by=user, file_hash=digest,
        status='ready', content_type=content_type, original_filename=Path(source.name.replace('\\', '/')).name[:255])
    try:
        with transaction.atomic():
            upload.source_file.save(source.name, source, save=False)
            upload.save()
    except Exception as exc:
        if upload.source_file.name:
            upload.source_file.storage.delete(upload.source_file.name)
        if isinstance(exc, IntegrityError):
            raise ValidationError('This document is already being processed. Reload the upload page.') from exc
        raise
    return upload


@transaction.atomic
def confirm_upload(user, business_id, pk, data):
    business = accessible_business(user, business_id)
    upload = get_object_or_404(PendingUpload.objects.select_for_update(), pk=pk, business=business, uploaded_by=user)
    if upload.confirmed_invoice_id:
        return upload.confirmed_invoice, None
    if upload.status == 'confirmed':
        raise ValidationError('This upload has already been confirmed; its invoice is no longer available.')
    form = ConfirmInvoiceForm(data)
    if not form.is_valid():
        return None, form
    if hashlib.sha256(Path(upload.source_file.path).read_bytes()).hexdigest() != upload.file_hash:
        raise ValidationError('The source document changed. Discard it and upload again.')
    existing = Invoice.objects.filter(business=business, file_hash=upload.file_hash).first()
    if existing:
        raise DuplicateDocument(existing)
    invoice = form.save(commit=False)
    invoice.business = business
    invoice.uploaded_by = user
    invoice.source_file.name = upload.source_file.name
    invoice.original_filename = upload.original_filename
    invoice.file_hash = upload.file_hash
    invoice.content_type = upload.content_type
    invoice.save()
    event(invoice, user, 'upload', new='draft', message='Invoice created after uploader confirmed its details.')
    upload.confirmed_invoice = invoice
    upload.status = 'confirmed'
    # Transfer file ownership; expiring the temporary record must not delete this file.
    upload.source_file.name = ''
    upload.save(update_fields=['confirmed_invoice', 'status', 'source_file'])
    return invoice, form
