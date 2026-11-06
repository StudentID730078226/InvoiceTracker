from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from accounts.models import Business, Membership


class ProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('profile-client')
        self.business = Business.objects.create(name='Only business')
        Membership.objects.create(user=self.user, business=self.business, role='client')

    def test_profile_requires_login_and_shows_only_assigned_businesses(self):
        self.assertEqual(self.client.get(reverse('profile')).status_code, 302)
        Business.objects.create(name='Private other business')
        self.client.force_login(self.user)
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Only business')
        self.assertContains(response, reverse('password_change'))
        self.assertContains(response, f'action="{reverse("logout")}"')
        self.assertContains(response, 'one business')
        self.assertNotContains(response, 'Private other business')

    def test_single_business_redirect_and_role_specific_dashboard(self):
        self.client.force_login(self.user)
        url = reverse('invoices:dashboard', args=[self.business.pk])
        self.assertRedirects(self.client.get(reverse('business_select')), url)
        response = self.client.get(url)
        self.assertNotContains(response, 'Switch business')
        self.assertNotContains(response, 'Awaiting your review')
        self.assertContains(response, 'aria-label="Your profile"')
        self.assertNotContains(response, f'action="{reverse("logout")}"')
        self.assertNotContains(response, 'Change password')
        Membership.objects.filter(user=self.user).update(role='accountant')
        self.assertContains(self.client.get(url), 'Awaiting your review')

    def test_multiple_businesses_have_switcher_and_per_business_roles(self):
        other = Business.objects.create(name='Second business')
        Membership.objects.create(user=self.user, business=other, role='accountant')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('business_select')).status_code, 200)
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Switch business')
        self.assertEqual([w['role'] for w in response.context['workspaces']], ['Client', 'Approver (Accountant)'])

    def test_admin_can_add_employee_and_employee_cannot_manage_users(self):
        admin = get_user_model().objects.create_user("org-admin", password="Testing-local-947!")
        Membership.objects.create(user=admin, business=self.business, role=Membership.Role.ADMIN)
        self.client.force_login(admin)
        response = self.client.post(
            reverse("add_member", args=[self.business.pk]),
            {"username": "new-employee", "email": "new@example.test",
             "password": "NewEmployee-947!", "role": Membership.Role.EMPLOYEE},
        )
        self.assertRedirects(response, reverse("members", args=[self.business.pk]))
        new_user = get_user_model().objects.get(username="new-employee")
        self.assertTrue(Membership.objects.filter(
            user=new_user, business=self.business, role=Membership.Role.EMPLOYEE,
        ).exists())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("members", args=[self.business.pk])).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("add_member", args=[self.business.pk]),
            {"username": "another", "password": "AnotherEmployee-947!", "role": Membership.Role.EMPLOYEE},
        ).status_code, 403)

    def test_admin_can_remove_employee_but_not_themselves_or_last_admin(self):
        admin = get_user_model().objects.create_user("remove-admin", password="Testing-local-947!")
        Membership.objects.create(user=admin, business=self.business, role=Membership.Role.ADMIN)
        employee = get_user_model().objects.create_user("remove-employee")
        employee_membership = Membership.objects.create(
            user=employee, business=self.business, role=Membership.Role.EMPLOYEE,
        )
        self.client.force_login(admin)
        response = self.client.post(reverse("remove_member", args=[self.business.pk, employee_membership.pk]))
        self.assertRedirects(response, reverse("members", args=[self.business.pk]))
        self.assertFalse(Membership.objects.filter(pk=employee_membership.pk).exists())
        admin_membership = Membership.objects.get(user=admin, business=self.business)
        self.client.post(reverse("remove_member", args=[self.business.pk, admin_membership.pk]))
        self.assertTrue(Membership.objects.filter(pk=admin_membership.pk).exists())
