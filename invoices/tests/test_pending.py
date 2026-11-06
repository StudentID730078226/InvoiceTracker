from datetime import timedelta
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import Business, Membership
from invoices.models import Invoice, PendingUpload
from invoices.pending import stage_upload, expire_uploads, confirm_upload, discard_upload
from invoices.tests.test_workflow import image_upload


class PendingUploadTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = override_settings(MEDIA_ROOT=temp.name)
        settings.enable(); self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user('pending-client')
        self.other = get_user_model().objects.create_user('pending-other')
        self.business = Business.objects.create(name='Pending business')
        for user in (self.user, self.other):
            Membership.objects.create(user=user, business=self.business, role='client')
        self.client.force_login(self.user)
        self.upload_url = reverse('invoices:upload', args=[self.business.pk])

    def staged(self):
        return stage_upload(self.user, self.business.pk, image_upload())

    def ready(self):
        return self.staged()

    def fields(self, **changes):
        values = {'supplier': 'Checked Supplier', 'invoice_number': 'CHECK-1', 'invoice_date': '2026-10-26',
                  'due_date': '2026-11-26', 'currency': 'GBP', 'total': '12.00', 'notes': '', 'confirm_details': 'on'}
        values.update(changes)
        return values

    def test_upload_opens_blank_manual_form_without_creating_invoice(self):
        response = self.client.post(self.upload_url, {'document': image_upload()})
        pending = PendingUpload.objects.get()
        self.assertEqual(pending.status, 'ready')
        self.assertRedirects(response, pending.get_absolute_url())
        self.assertFalse(Invoice.objects.exists())
        response = self.client.get(pending.get_absolute_url())
        self.assertContains(response, 'Enter invoice details')
        self.assertContains(response, 'Confirm details and save invoice')
        self.assertFalse(response.context['form'].initial)
        self.assertNotContains(response, 'Scanning automatically')
        self.assertNotContains(response, 'window.setTimeout')

    def test_pending_extraction_button_queues_scan_without_creating_invoice(self):
        pending = self.ready()
        with patch("invoices.extraction._worker_python") as python:
            python.return_value.is_file.return_value = True
            with patch("invoices.extraction._launch_pending_worker") as launch:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        reverse("invoices:pending_extract", args=[self.business.pk, pending.pk])
                    )
        self.assertRedirects(response, pending.get_absolute_url())
        pending.refresh_from_db()
        self.assertEqual(pending.status, "queued")
        launch.assert_called_once_with(pending.pk)
        self.assertFalse(Invoice.objects.exists())

    def test_pending_extraction_suggestions_fill_confirmation_form(self):
        pending = self.ready()
        PendingUpload.objects.filter(pk=pending.pk).update(
            status="succeeded",
            suggestions={"supplier": "Suggested Supplier", "invoice_number": "S-1", "total": "12.00"},
        )
        response = self.client.get(pending.get_absolute_url())
        self.assertEqual(response.context["form"].initial["supplier"], "Suggested Supplier")
        self.assertEqual(response.context["form"].initial["total"], "12.00")
        self.assertContains(response, "Suggested values have been placed in the form")

    def test_confirmation_requires_checked_fields_and_explicit_confirmation(self):
        pending = self.ready()
        for data in (self.fields(confirm_details=''), self.fields(supplier=''), self.fields(total='-1')):
            response = self.client.post(pending.get_absolute_url(), data)
            self.assertTrue(response.context['form'].errors)
            self.assertFalse(Invoice.objects.exists())
        response = self.client.post(pending.get_absolute_url(), self.fields(status='approved'))
        invoice = Invoice.objects.get()
        self.assertRedirects(response, invoice.get_absolute_url())
        self.assertEqual(invoice.status, 'draft')
        self.assertIsNone(invoice.approved_at)
        self.assertEqual(invoice.supplier, 'Checked Supplier')
        self.assertFalse(invoice.extractions.exists())
        self.client.post(pending.get_absolute_url(), self.fields())
        self.assertEqual(Invoice.objects.count(), 1)

    def test_file_ownership_transfers_and_expiration_cannot_remove_saved_source(self):
        pending = self.ready()
        source = Path(pending.source_file.path)
        invoice, _ = confirm_upload(self.user, self.business.pk, pending.pk, self.fields())
        PendingUpload.objects.filter(pk=pending.pk).update(created_at=timezone.now()-timedelta(days=2))
        with self.captureOnCommitCallbacks(execute=True): expire_uploads()
        self.assertTrue(source.exists())
        self.assertEqual(Path(invoice.source_file.path), source)
        self.assertFalse(PendingUpload.objects.exists())

    def test_cancel_and_expiration_delete_only_unconfirmed_files(self):
        pending = self.staged()
        source = Path(pending.source_file.path)
        url = reverse('invoices:pending_discard', args=[self.business.pk, pending.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        with self.captureOnCommitCallbacks(execute=True): self.client.post(url)
        self.assertFalse(source.exists()); self.assertFalse(Invoice.objects.exists())
        pending = self.staged(); source = Path(pending.source_file.path)
        PendingUpload.objects.filter(pk=pending.pk).update(created_at=timezone.now()-timedelta(days=2))
        with self.captureOnCommitCallbacks(execute=True): expire_uploads()
        self.assertFalse(source.exists())

    def test_temporary_upload_is_private_even_from_another_business_member(self):
        pending = self.ready()
        self.client.force_login(self.other)
        for url in (pending.get_absolute_url(), reverse('invoices:pending_media', args=[self.business.pk, pending.pk])):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(pending.get_absolute_url(), self.fields()).status_code, 404)
        self.client.force_login(self.user)
        browser = Client(enforce_csrf_checks=True); browser.force_login(self.user)
        self.assertEqual(browser.post(pending.get_absolute_url(), self.fields()).status_code, 403)
        media = self.client.get(reverse('invoices:pending_media', args=[self.business.pk, pending.pk]), {'strength': 4})
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media['Cache-Control'], 'private, no-store')
        self.assertEqual(b''.join(media.streaming_content), image_upload().read())
        media.close()

    def test_old_pending_scan_suggestions_are_not_used(self):
        pending = self.staged()
        PendingUpload.objects.filter(pk=pending.pk).update(status='running', suggestions={'supplier': 'Old prediction'})
        response = self.client.get(pending.get_absolute_url())
        self.assertFalse(response.context['form'].initial)
        self.assertNotContains(response, 'Old prediction')
        self.client.post(pending.get_absolute_url(), self.fields())
        self.assertEqual(Invoice.objects.get().supplier, 'Checked Supplier')

    def test_scanning_routes_are_removed(self):
        invoice, _ = confirm_upload(self.user, self.business.pk, self.ready().pk, self.fields())
        base = invoice.get_absolute_url()
        for suffix in ('contrast/', 'extractions/1/apply/', 'extractions/1/review/'):
            self.assertEqual(self.client.post(base + suffix).status_code, 404)
        response = self.client.get(base)
        self.assertContains(response, 'Edit invoice details')
        self.assertContains(response, 'Combined model scan')

    def test_confirmed_file_survives_discard_of_stale_pending_object(self):
        pending = self.ready()
        source = Path(pending.source_file.path)
        confirm_upload(self.user, self.business.pk, pending.pk, self.fields())
        with self.captureOnCommitCallbacks(execute=True): discard_upload(pending)
        self.assertTrue(source.exists())

    def test_pending_uploads_are_not_in_invoice_lists_spending_or_counts(self):
        self.ready()
        response = self.client.get(reverse('invoices:dashboard', args=[self.business.pk]))
        self.assertContains(response, 'Uploads awaiting your confirmation')
        self.assertEqual(sum(count for label, count in response.context['counts']), 0)
        response = self.client.get(reverse('invoices:spending', args=[self.business.pk]))
        self.assertEqual(response.context['spending']['invoice_count'], 0)
        response = self.client.get(reverse('invoices:list', args=[self.business.pk]))
        self.assertEqual(response.context['page_obj'].paginator.count, 0)
