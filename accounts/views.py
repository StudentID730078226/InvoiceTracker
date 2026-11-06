from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from .forms import AddOrganisationUserForm
from .services import accessible_business, can_admin, permitted_businesses
from .models import Membership


@login_required
def business_select(request):
    businesses = permitted_businesses(request.user)
    if businesses.count() == 1:
        return redirect("invoices:dashboard", business_id=businesses.first().pk)
    return render(request, "accounts/business_select.html", {"businesses": businesses})


@login_required
def profile(request):
    roles = dict(Membership.objects.filter(user=request.user).values_list('business_id', 'role'))
    workspaces = [{'business': business,
                   'role': ('Administrator' if roles.get(business.pk) == 'admin' else 'Employee')
                   if roles.get(business.pk) in ('admin', 'employee')
                   else ('Approver (Accountant)' if request.user.is_superuser or roles.get(business.pk) == 'accountant' else 'Client')}
                  for business in permitted_businesses(request.user)]
    return render(request, 'accounts/profile.html', {'workspaces': workspaces})


@login_required
def members(request, business_id):
    business = accessible_business(request.user, business_id)
    if not can_admin(request.user, business):
        raise PermissionDenied("Only administrators can manage organisation users.")
    return render(request, "accounts/members.html", {
        "business": business,
        "can_admin": True,
        "memberships": Membership.objects.filter(business=business).select_related("user"),
        "form": AddOrganisationUserForm(),
    })


@login_required
@require_http_methods(["POST"])
def add_member(request, business_id):
    business = accessible_business(request.user, business_id)
    if not can_admin(request.user, business):
        raise PermissionDenied("Only administrators can manage organisation users.")
    form = AddOrganisationUserForm(request.POST)
    if form.is_valid():
        User = get_user_model()
        user = User.objects.create_user(
            username=form.cleaned_data["username"],
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        Membership.objects.create(user=user, business=business, role=form.cleaned_data["role"])
        messages.success(request, f"{user.username} was added to {business.name}.")
        return redirect("members", business_id=business.pk)
    return render(request, "accounts/members.html", {
        "business": business,
        "can_admin": True,
        "memberships": Membership.objects.filter(business=business).select_related("user"),
        "form": form,
    }, status=400)


@login_required
@require_http_methods(["POST"])
def remove_member(request, business_id, membership_id):
    business = accessible_business(request.user, business_id)
    if not can_admin(request.user, business):
        raise PermissionDenied("Only administrators can manage organisation users.")
    membership = get_object_or_404(
        Membership.objects.select_related("user").filter(business=business),
        pk=membership_id,
    )
    if membership.user_id == request.user.id:
        messages.error(request, "You cannot remove your own organisation access.")
    elif membership.role in (Membership.Role.ADMIN, Membership.Role.ACCOUNTANT) and not Membership.objects.filter(
        business=business, role__in=(Membership.Role.ADMIN, Membership.Role.ACCOUNTANT)
    ).exclude(pk=membership.pk).exists():
        messages.error(request, "The organisation must keep at least one administrator.")
    else:
        username = membership.user.username
        membership.delete()
        messages.success(request, f"{username} was removed from {business.name}.")
    return redirect("members", business_id=business.pk)
