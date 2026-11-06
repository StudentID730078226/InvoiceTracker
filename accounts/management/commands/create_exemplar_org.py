from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from accounts.models import Business, Membership


class Command(BaseCommand):
    help = "Create the local exemplar organisation with an administrator and employee."

    def handle(self, *args, **options):
        User = get_user_model()
        business, _ = Business.objects.get_or_create(name="Exemplar Organisation")
        admin, _ = User.objects.get_or_create(username="exemplar_admin", defaults={"email": "admin@exemplar.local"})
        admin.email = "admin@exemplar.local"
        admin.set_password("ExemplarInvoice-2026!")
        admin.save()
        employee, _ = User.objects.get_or_create(username="exemplar_employee", defaults={"email": "employee@exemplar.local"})
        employee.email = "employee@exemplar.local"
        employee.set_password("ExemplarInvoice-2026!")
        employee.save()
        Membership.objects.update_or_create(user=admin, business=business, defaults={"role": Membership.Role.ADMIN})
        Membership.objects.update_or_create(user=employee, business=business, defaults={"role": Membership.Role.EMPLOYEE})
        self.stdout.write(self.style.SUCCESS(
            "Exemplar Organisation ready: exemplar_admin / exemplar_employee, password ExemplarInvoice-2026!"
        ))
