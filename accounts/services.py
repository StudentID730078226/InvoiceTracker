from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .models import Business, Membership


def permitted_businesses(user):
    businesses = Business.objects.filter(active=True)
    if not user.is_active:
        return businesses.none()
    if user.is_superuser:
        return businesses
    return businesses.filter(memberships__user=user).distinct()


def accessible_business(user, business_id):
    return get_object_or_404(permitted_businesses(user), pk=business_id)


def can_review(user, business):
    return can_admin(user, business)


def can_admin(user, business):
    return user.is_active and (user.is_superuser or Membership.objects.filter(
        user=user, business=business,
        role__in=(Membership.Role.ADMIN, Membership.Role.ACCOUNTANT),
    ).exists())


def can_submit(user, business):
    return user.is_active and (user.is_superuser or Membership.objects.filter(
        user=user, business=business,
        role__in=(Membership.Role.EMPLOYEE, Membership.Role.CLIENT, Membership.Role.ADMIN, Membership.Role.ACCOUNTANT),
    ).exists())


def role_for(user, business):
    if user.is_superuser:
        return "admin"
    membership = Membership.objects.filter(user=user, business=business).first()
    if not membership:
        return ""
    if membership.role == Membership.Role.ADMIN:
        return "admin"
    if membership.role == Membership.Role.EMPLOYEE:
        return "employee"
    return "legacy-admin" if membership.role == Membership.Role.ACCOUNTANT else "legacy-client"


def require_reviewer(user, business):
    if not can_admin(user, business):
        raise PermissionDenied("Only administrators can review or export invoices.")
