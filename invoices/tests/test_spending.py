from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from accounts.models import Business, Membership
from invoices.models import Invoice


class SpendingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('spending-user')
        self.business = Business.objects.create(name='Spending business')
        self.other = Business.objects.create(name='Private business')
        Membership.objects.create(user=self.user, business=self.business, role='client')
        self.client.force_login(self.user)
        self.counter = 0
        self.make(total='10.10', invoice_date=date(2026, 1, 5), status='submitted', supplier='Acme')
        self.make(total='20.20', invoice_date=date(2026, 3, 9), status='approved', supplier=' acme ')
        self.make(total='500', status='draft')
        self.make(total='600', status='returned')
        self.make(total='900', currency='EUR')
        self.make(total='999', business=self.other)
        self.url = reverse('invoices:spending', args=[self.business.pk])
        self.params = {'date_from': '2026-01-01', 'date_to': '2026-03-31', 'currency': 'GBP',
                       'status': 'submitted_approved', 'granularity': 'month'}

    def make(self, **kwargs):
        self.counter += 1
        fields = {'business': self.business, 'uploaded_by': self.user, 'invoice_date': date(2026, 2, 1),
                  'currency': 'GBP', 'status': 'submitted', 'supplier': 'Other supplier',
                  'file_hash': f'{self.counter:064x}'}
        fields.update(kwargs)
        return Invoice.objects.create(**fields)

    def result(self, **kwargs):
        response = self.client.get(self.url, {**self.params, **kwargs})
        self.assertEqual(response.status_code, 200)
        return response.context['spending']

    def test_totals_exclude_other_businesses_currencies_and_unsubmitted_records(self):
        result = self.result()
        self.assertEqual(result['total'], Decimal('30.30'))
        self.assertEqual(result['invoice_count'], 2)
        self.assertEqual(result['average'], Decimal('15.15'))
        self.assertEqual([Decimal(p['total']) for p in result['periods']], [Decimal('10.10'), Decimal('0'), Decimal('20.20')])
        self.assertEqual(len(result['suppliers']), 1)
        self.assertEqual(result['suppliers'][0]['count'], 2)

    def test_filters_are_inclusive_and_allow_supplier_and_status_selection(self):
        self.assertEqual(self.result(supplier='ACME', status='approved')['total'], Decimal('20.20'))
        self.assertEqual(self.result(date_from='2026-01-05', date_to='2026-01-05')['total'], Decimal('10.10'))
        self.assertEqual(self.result(currency='EUR')['total'], Decimal('900'))
        self.assertEqual(self.result(status='all')['total'], Decimal('1130.30'))

    def test_granularities_preserve_totals_and_weeks_start_monday(self):
        for unit in ('day', 'week', 'month', 'quarter', 'year'):
            result = self.result(granularity=unit)
            self.assertEqual(sum(Decimal(p['total']) for p in result['periods']), Decimal('30.30'))
        self.assertEqual(self.result(granularity='week')['periods'][0]['label'], '2025-12-29')
        self.assertEqual(self.result(granularity='quarter')['periods'][0]['label'], '2026 Q1')

    def test_incomplete_records_reported_and_zero_amount_is_counted(self):
        self.make(total='0', supplier='Zero invoice')
        self.make(total=None)
        self.make(total='50', invoice_date=None)
        result = self.result()
        self.assertEqual(result['invoice_count'], 3)
        self.assertEqual(result['total'], Decimal('30.30'))
        self.assertEqual(result['undated'], 1)
        self.assertEqual(result['incomplete'], 1)

    def test_invalid_filters_and_excessively_detailed_ranges_show_errors(self):
        for params in ({'date_to': '2025-01-01'}, {'currency': 'XXX'}, {'granularity': 'invalid'},
                       {'date_from': '2000-01-01', 'date_to': '2030-01-01', 'granularity': 'day'}):
            response = self.client.get(self.url, {**self.params, **params})
            self.assertTrue(response.context['filter_form'].errors)
            self.assertIsNone(response.context['spending'])

    def test_authorization_empty_state_and_script_escaping(self):
        self.assertEqual(self.client.get(reverse('invoices:spending', args=[self.other.pk])).status_code, 404)
        self.assertContains(self.client.get(self.url, {**self.params, 'supplier': 'Absent'}), 'No matching invoices')
        self.make(total='1', supplier='</script><script>alert(1)</script>')
        response = self.client.get(self.url, self.params)
        self.assertNotContains(response, '</script><script>alert(1)</script>')
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
