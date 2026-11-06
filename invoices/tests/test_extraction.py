import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import QueryDict

from accounts.models import Business, Membership
from invoices.extraction import apply_suggestions, normalize_suggestions, load_extraction_result
from invoices.models import ExtractionRun, Invoice
from invoices.tests.test_workflow import image_upload
from invoices.services import create_upload


class ExtractionTests(TestCase):
    def test_result_loader_normalizes_fields_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            path.write_text(json.dumps({
                "suggestions": {"supplier": "Example", "invoice_date": "05/27/18", "total": "$170.00"},
                "warnings": ["Check the source"], "model_version": "test-model",
            }), encoding="utf-8")
            result = load_extraction_result(path)
        self.assertEqual(result["suggestions"]["invoice_date"], "2018-05-27")
        self.assertEqual(result["suggestions"]["total"], "170.00")
        self.assertEqual(result["suggestions"]["currency"], "USD")
        self.assertEqual(result["warnings"], ["Check the source"])
        self.assertEqual(result["model_version"], "test-model")

    def test_result_loader_omits_invalid_fields_without_losing_valid_ones(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            path.write_text(json.dumps({"suggestions": {
                "supplier": "Example", "invoice_date": "not a date", "total": "-5.00",
            }}), encoding="utf-8")
            result = load_extraction_result(path)
        self.assertEqual(result["suggestions"]["supplier"], "Example")
        self.assertNotIn("invoice_date", result["suggestions"])
        self.assertNotIn("total", result["suggestions"])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        override = override_settings(MEDIA_ROOT=temp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user("extract-user")
        self.business = Business.objects.create(name="Extraction business")
        Membership.objects.create(user=self.user, business=self.business, role="client")
        self.invoice = create_upload(self.user, self.business.pk, image_upload())
        self.client.force_login(self.user)

    def test_start_requires_worker_and_creates_queued_run(self):
        with patch("invoices.extraction._worker_python") as python:
            python.return_value.is_file.return_value = True
            with patch("invoices.extraction.launch_worker") as launch:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        reverse("invoices:extraction_start", args=[self.business.pk, self.invoice.pk])
                    )
        self.assertEqual(response.status_code, 302)
        run = ExtractionRun.objects.get()
        self.assertEqual(run.status, ExtractionRun.Status.QUEUED)
        launch.assert_called_once_with(run.pk)

    def test_suggestions_require_explicit_selection(self):
        run = ExtractionRun.objects.create(
            invoice=self.invoice, requested_by=self.user, source_hash=self.invoice.file_hash,
            invoice_revision=self.invoice.updated_at, status=ExtractionRun.Status.SUCCEEDED,
            suggestions={"supplier": "Suggested Supplier", "total": "12.34"},
        )
        with self.assertRaisesMessage(ValidationError, "Select at least one"):
            apply_suggestions(self.user, self.business.pk, self.invoice.pk, run.pk, QueryDict())
        self.assertEqual(Invoice.objects.get(pk=self.invoice.pk).supplier, "")

    def test_normalize_model_values_for_confirmation_form(self):
        suggestions = normalize_suggestions({
            "supplier": "PORTLAND RADIO GROUP",
            "invoice_number": "IN-12010111678",
            "invoice_date": "10/25/2020",
            "due_date": "25-February-2026",
            "total": "$4,250.00",
        })
        self.assertEqual(suggestions["invoice_date"], "2020-10-25")
        self.assertEqual(suggestions["due_date"], "2026-02-25")
        self.assertEqual(suggestions["total"], "4250.00")
        self.assertEqual(suggestions["currency"], "USD")
