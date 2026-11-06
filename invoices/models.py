from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


def source_path(instance, filename):
    return f"documents/{uuid4().hex}{Path(filename).suffix.lower()}"


class Invoice(models.Model):
    """Persist invoice data and relationships through Django's ORM (MVT Model).

    Views retrieve these records; templates display them. Workflow services
    enforce who may change a record or move it between review states.
    """

    class Status(models.TextChoices):
        """Stored state codes paired with human-readable display labels."""
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        RETURNED = "returned", "Returned"
        APPROVED = "approved", "Approved"

    CURRENCIES = [("GBP", "GBP"), ("EUR", "EUR"), ("USD", "USD")]
    # Ownership links support organisation-scoped access checks in the view/service.
    business = models.ForeignKey("accounts.Business", on_delete=models.PROTECT, related_name="invoices")
    # FileField stores a storage reference, not the document's image bytes in SQL.
    source_file = models.FileField(upload_to=source_path)
    original_filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64)
    content_type = models.CharField(max_length=30)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_invoices")
    # Incomplete drafts are allowed; submission services require the core values.
    supplier = models.CharField(max_length=200, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCIES, blank=True)
    total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    notes = models.TextField(blank=True)
    # Review state and provenance are separate from the invoice's financial fields.
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    return_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_invoices", null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # Stable newest-first ordering; database constraints also protect integrity.
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["business", "file_hash"], name="unique_business_document"),
            models.CheckConstraint(condition=models.Q(total__gte=0) | models.Q(total__isnull=True), name="invoice_total_nonnegative"),
        ]

    @property
    def editable(self):
        """Identify ordinary editing states; services check actor permissions too."""
        return self.status in [self.Status.DRAFT, self.Status.RETURNED]

    def get_absolute_url(self):
        """Build the named detail route for this record and its organisation."""
        return reverse("invoices:detail", kwargs={"business_id": self.business_id, "pk": self.pk})

    def __str__(self):
        return self.invoice_number or f"Invoice {self.pk}"


class InvoiceEvent(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    event_type = models.CharField(max_length=30)
    old_status = models.CharField(max_length=12, blank=True)
    new_status = models.CharField(max_length=12, blank=True)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class ExtractionRun(models.Model):
    """Scan record for a saved draft invoice."""
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Reading document"
        SUCCEEDED = "succeeded", "Ready for review"
        FAILED = "failed", "Could not extract"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="extractions")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    source_hash = models.CharField(max_length=64)
    invoice_revision = models.DateTimeField()
    suggestions = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    error = models.TextField(blank=True)
    model_version = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    enhancement_strength = models.PositiveSmallIntegerField(default=4)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["invoice"], condition=models.Q(status__in=["queued", "running"]),
                                              name="one_active_extraction_per_invoice")]


class PendingUpload(models.Model):
    """Private temporary document; no Invoice exists until the uploader confirms details."""
    business = models.ForeignKey('accounts.Business', on_delete=models.CASCADE)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source_file = models.FileField(upload_to=source_path)
    original_filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64)
    content_type = models.CharField(max_length=30)
    status = models.CharField(max_length=12, default='queued')
    suggestions = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    error = models.TextField(blank=True)
    model_version = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    confirmed_invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['business', 'file_hash'], name='unique_pending_business_document')]

    def get_absolute_url(self):
        return reverse('invoices:pending_review', kwargs={'business_id': self.business_id, 'pk': self.pk})
