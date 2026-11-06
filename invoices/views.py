import csv
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from accounts.services import accessible_business, can_admin, can_review, can_submit, require_reviewer, role_for
from .forms import FilterForm, InvoiceForm, ReturnForm, SubmitForm, UploadForm
from .models import Invoice, PendingUpload
from .pending import stage_upload, confirm_upload, discard_upload
from .forms import ConfirmInvoiceForm
from .forms import SpendingFilterForm
from .spending import build_spending
from django.utils import timezone
from .services import (DuplicateDocument, csv_safe, delete_draft, edit_invoice,
                       possible_duplicates, transition_invoice)
from .extraction import (apply_suggestions, review_form, start_extraction,
                         start_pending_extraction)


def context(request, business):
    role = role_for(request.user, business)
    return {"business": business, "can_review": can_review(request.user, business),
            "can_admin": can_admin(request.user, business), "can_submit": can_submit(request.user, business),
            "workspace_role": role}


def scoped_invoice(request, business_id, pk):
    business = accessible_business(request.user, business_id)
    records = Invoice.objects.filter(business=business, pk=pk)
    if not can_admin(request.user, business):
        records = records.filter(uploaded_by=request.user)
    return business, get_object_or_404(records)


def filtered_invoices(business, data, export=False):
    form = FilterForm(data)
    records = Invoice.objects.filter(business=business).select_related('uploaded_by')
    if form.is_valid():
        filters = form.cleaned_data
        if filters.get("q"):
            records = records.filter(Q(supplier__icontains=filters["q"]) | Q(invoice_number__icontains=filters["q"]))
        if filters.get("status") and not export:
            records = records.filter(status=filters["status"])
        if filters.get("date_from"):
            records = records.filter(invoice_date__gte=filters["date_from"])
        if filters.get("date_to"):
            records = records.filter(invoice_date__lte=filters["date_to"])
    else:
        records = records.none()
    return records, form


@login_required
def dashboard(request, business_id):
    business = accessible_business(request.user, business_id)
    records = Invoice.objects.filter(business=business)
    if not can_admin(request.user, business):
        records = records.filter(uploaded_by=request.user)
    counts = dict(records.values("status").annotate(count=Count("pk")).values_list("status", "count"))
    return render(request, "invoices/dashboard.html", {**context(request, business),
        "counts": [(label, counts.get(status, 0)) for status, label in Invoice.Status.choices],
        "recent": records[:8],
        "pending_uploads": PendingUpload.objects.filter(business=business, uploaded_by=request.user).exclude(status='confirmed'),
        "pending_review": Invoice.objects.filter(business=business, status=Invoice.Status.SUBMITTED)[:8] if can_review(request.user, business) else []})


@login_required
def spending(request, business_id):
    business = accessible_business(request.user, business_id)
    if role_for(request.user, business) == "employee":
        raise PermissionDenied("Only administrators can view expenditure.")
    today = timezone.localdate()
    currencies = set(Invoice.objects.filter(business=business, status__in=['submitted', 'approved']).values_list('currency', flat=True))
    default_currency = next((code for code in ('GBP', 'EUR', 'USD') if code in currencies), 'GBP')
    defaults = {'date_from': today.replace(month=1, day=1).isoformat(), 'date_to': today.isoformat(),
                'currency': default_currency, 'status': 'submitted_approved', 'granularity': 'month'}
    form = SpendingFilterForm({**defaults, **request.GET.dict()})
    result = None
    if form.is_valid():
        try:
            result = build_spending(business, form.cleaned_data)
        except ValueError as exc:
            form.add_error('granularity', str(exc))
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'invoices/spending.html', {**context(request, business), 'filter_form': form,
        'spending': result, 'currency': form.cleaned_data.get('currency', default_currency),
        'page_obj': Paginator(result['records'], 20).get_page(request.GET.get('page')) if result else None,
        'filter_query': query.urlencode()})


@login_required
def invoice_list(request, business_id):
    business = accessible_business(request.user, business_id)
    records, form = filtered_invoices(business, request.GET)
    if role_for(request.user, business) == "employee":
        records = records.filter(uploaded_by=request.user)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "invoices/list.html", {**context(request, business), "filter_form": form,
        "page_obj": Paginator(records, 20).get_page(request.GET.get("page")), "filter_query": query.urlencode(),
        "review_queue": can_admin(request.user, business) and request.GET.get("status") == Invoice.Status.SUBMITTED})


@login_required
def review_queue(request, business_id):
    business = accessible_business(request.user, business_id)
    if not can_admin(request.user, business):
        raise PermissionDenied("Only administrators can review invoices.")
    return redirect(f"{reverse('invoices:list', args=[business.pk])}?status={Invoice.Status.SUBMITTED}")


@login_required
def upload(request, business_id):
    business = accessible_business(request.user, business_id)
    form = UploadForm(request.POST if request.method == "POST" else None,
                      request.FILES if request.method == "POST" else None)
    duplicate = None
    if request.method == "POST" and form.is_valid():
        try:
            pending = stage_upload(request.user, business.pk, form.cleaned_data["document"])
        except DuplicateDocument as exc:
            duplicate = exc.invoice
            form.add_error("document", exc)
        except ValidationError as exc:
            form.add_error("document", exc)
        else:
            messages.success(request, 'Document uploaded. Enter and confirm its details to save the invoice.')
            return redirect(pending)
    return render(request, "invoices/upload.html", {**context(request, business), "form": form, "duplicate": duplicate})


def scoped_pending(request, business_id, pk):
    business = accessible_business(request.user, business_id)
    return business, get_object_or_404(PendingUpload, business=business, pk=pk, uploaded_by=request.user)


@login_required
def pending_review(request, business_id, pk):
    business, pending = scoped_pending(request, business_id, pk)
    if pending.confirmed_invoice_id:
        return redirect(pending.confirmed_invoice)
    initial = pending.suggestions if pending.status == "succeeded" else {}
    form = ConfirmInvoiceForm(initial=initial)
    if initial:
        for name in initial:
            if name in form.fields:
                form.fields[name].help_text = "Suggested value. Check it against the invoice."
    if request.method == 'POST':
        try:
            invoice, form = confirm_upload(request.user, business.pk, pk, request.POST)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
            return redirect(pending)
        if invoice:
            messages.success(request, 'Details confirmed and invoice saved. Accountant approval is a separate review step.')
            return redirect(invoice)
    return render(request, 'invoices/pending_review.html', {**context(request, business),     'pending': pending, 'form': form})


@login_required
@require_POST
def pending_extract(request, business_id, pk):
    business, pending = scoped_pending(request, business_id, pk)
    try:
        start_pending_extraction(request.user, business.pk, pending.pk)
    except (ValidationError, RuntimeError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Invoice extraction started. Reload this page when the scan is ready.')
    return redirect(pending)


@login_required
@require_POST
def pending_discard(request, business_id, pk):
    business, pending = scoped_pending(request, business_id, pk)
    if pending.status == 'confirmed':
        return redirect('invoices:list', business_id=business.pk)
    discard_upload(pending)
    messages.success(request, 'Temporary upload discarded. No invoice was saved.')
    return redirect('invoices:upload', business_id=business.pk)


@login_required
def pending_media(request, business_id, pk):
    business, pending = scoped_pending(request, business_id, pk)
    if not pending.source_file.name:
        raise Http404('Temporary upload is no longer available.')
    try:
        response = FileResponse(pending.source_file.open('rb'), content_type=pending.content_type,
                                filename=pending.original_filename,
                                as_attachment=pending.content_type == 'application/pdf' or request.GET.get('source') == '1')
    except FileNotFoundError as exc:
        raise Http404('Temporary file is unavailable.') from exc
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
def invoice_detail(request, business_id, pk):
    """Handle the invoice-detail request and render its context (MVT View).

    Authentication is enforced by the decorator. The scoped lookup checks
    organisation membership and record visibility before any data is rendered.
    """
    # Retrieve the permitted business and Invoice model instance, not a global ID.
    business, invoice = scoped_invoice(request, business_id, pk)

    # Pass model data, role flags and unbound action forms to the template.
    # This GET handler displays information; it does not change invoice state.
    page_context = {
        **context(request, business),
        "invoice": invoice,
        "latest_extraction": invoice.extractions.first(),
        "duplicates": possible_duplicates(invoice) if invoice.editable else [],
        "submit_form": SubmitForm(),
        "return_form": ReturnForm(),
    }

    # Django renders the selected template as an HTML HTTP response.
    return render(request, "invoices/detail.html", page_context)


@login_required
@require_POST
def extraction_start(request, business_id, pk):
    business, invoice = scoped_invoice(request, business_id, pk)
    try:
        run = start_extraction(request.user, business.pk, invoice.pk)
    except (ValidationError, RuntimeError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Combined model scan #{run.pk} started. Results will be presented when extraction completes")
    return redirect(invoice)


@login_required
def extraction_review(request, business_id, pk, run_id):
    business, invoice = scoped_invoice(request, business_id, pk)
    run = get_object_or_404(invoice.extractions, pk=run_id)
    if run.status != run.Status.SUCCEEDED:
        messages.info(request, "This scan is not ready for review yet.")
        return redirect(invoice)
    form = review_form(invoice, run)
    if request.method == "POST":
        try:
            invoice, form = apply_suggestions(request.user, business.pk, invoice.pk, run.pk, request.POST)
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            if not form.errors:
                messages.success(request, "Selected model suggestions were saved after your confirmation.")
                return redirect(invoice)
    return render(request, "invoices/extraction_review.html",
                  {**context(request, business), "invoice": invoice, "run": run, "form": form})


@login_required
def edit(request, business_id, pk):
    business, invoice = scoped_invoice(request, business_id, pk)
    if not invoice.editable and not (invoice.status == Invoice.Status.APPROVED and can_admin(request.user, business)):
        raise PermissionDenied("Submitted and approved invoices are read-only.")
    form = InvoiceForm(instance=invoice)
    if request.method == "POST":
        try:
            invoice, form = edit_invoice(request.user, business_id, pk, request.POST)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(invoice)
        if form.is_valid():
            messages.success(request, "Invoice details saved.")
            return redirect(invoice)
    return render(request, "invoices/edit.html", {**context(request, business), "invoice": invoice, "form": form})


@login_required
def source(request, business_id, pk):
    business, invoice = scoped_invoice(request, business_id, pk)
    try:
        handle = invoice.source_file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Document is unavailable.") from exc
    response = FileResponse(handle, content_type=invoice.content_type, filename=invoice.original_filename,
                            as_attachment=invoice.content_type == "application/pdf" or request.GET.get("download") == "1")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def transition(request, business_id, pk, action):
    business, invoice = scoped_invoice(request, business_id, pk)
    if action in {"approve", "return"}:
        require_reviewer(request.user, business)
    form = ReturnForm(request.POST) if action == "return" else SubmitForm(request.POST)
    if not form.is_valid():
        return render(request, "invoices/action_error.html", {**context(request, business), "invoice": invoice, "errors": form.errors}, status=400)
    try:
        invoice = transition_invoice(request.user, business_id, pk, action,
            reason=form.cleaned_data.get("reason", ""), acknowledge=form.cleaned_data.get("acknowledge_duplicate", False))
    except ValidationError as exc:
        return render(request, "invoices/action_error.html", {**context(request, business), "invoice": invoice, "errors": exc.messages}, status=400)
    messages.success(request, f"Invoice {invoice.get_status_display().lower()}.")
    return redirect(invoice)


@login_required
def delete(request, business_id, pk):
    business, invoice = scoped_invoice(request, business_id, pk)
    if not invoice.editable and not (invoice.status == Invoice.Status.APPROVED and can_admin(request.user, business)):
        raise PermissionDenied("Only draft and returned invoices can be deleted.")
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            return HttpResponse("Deletion confirmation is required.", status=400)
        try:
            delete_draft(request.user, business_id, pk)
        except ValidationError as exc:
            return HttpResponse(" ".join(exc.messages), status=400)
        messages.success(request, "Invoice and source document deleted.")
        return redirect("invoices:list", business_id=business_id)
    return render(request, "invoices/delete.html", {**context(request, business), "invoice": invoice})


@login_required
def export(request, business_id):
    business = accessible_business(request.user, business_id)
    require_reviewer(request.user, business)
    records, form = filtered_invoices(business, request.GET, export=True)
    if not form.is_valid():
        return HttpResponse("Invalid export filters.", status=400)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="approved-invoices.csv"'
    response["Cache-Control"] = "private, no-store"
    writer = csv.writer(response)
    writer.writerow(["supplier", "invoice_number", "invoice_date", "due_date", "currency", "total", "approved_at"])
    for invoice in records.filter(status=Invoice.Status.APPROVED):
        writer.writerow([csv_safe(invoice.supplier), csv_safe(invoice.invoice_number), invoice.invoice_date,
                         invoice.due_date or "", invoice.currency, f"{invoice.total:.2f}", invoice.approved_at.isoformat()])
    return response
