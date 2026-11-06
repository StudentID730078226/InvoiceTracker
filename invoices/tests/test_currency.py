import unittest
from invoices.currency import infer_currency, apply_currency_evidence


def word(text, x=.1, y=.1):
    return {'text': text, 'bbox': [x, y, x+.03, y+.02]}


class CurrencyEvidenceTests(unittest.TestCase):
    def test_separate_pound_sign_next_to_amount(self):
        self.assertEqual(infer_currency([word('£'), word('125.00', .14)])['currency'], 'GBP')

    def test_separate_dollar_sign_next_to_amount(self):
        result = infer_currency([word('$'), word('125.00', .14)])
        self.assertEqual(result['currency'], 'USD')
        self.assertTrue(result['dollar_assumption'])

    def test_attached_and_fullwidth_symbols(self):
        for text, expected in [('£125.00','GBP'), ('＄125.00','USD'), ('€125.00','EUR')]:
            with self.subTest(text=text):
                self.assertEqual(infer_currency([word(text)])['currency'], expected)

    def test_conflicting_currencies_abstain(self):
        self.assertIsNone(infer_currency([word('GBP'), word('USD')])['currency'])

    def test_unsupported_dollars_do_not_become_usd(self):
        self.assertIsNone(infer_currency([word('CAD'),word('$125.00')])['currency'])

    def test_do_not_guess_misread_letters(self):
        for text in ['E125.00', 'S125.00', 'L125.00']:
            self.assertIsNone(infer_currency([word(text)])['currency'])

    def test_isolated_symbol_unrelated_to_amount_abstains(self):
        self.assertIsNone(infer_currency([word('$'),word('125.00', .8,.8)])['currency'])

    def test_total_marker_can_supply_evidence(self):
        self.assertEqual(infer_currency([], '£125.00')['currency'], 'GBP')

    def test_no_cross_page_neighbors(self):
        a,b=word('£'),word('125.00',.14)
        a['page'],b['page']=0,1
        self.assertIsNone(infer_currency([a,b])['currency'])

    def test_selected_total_currency_takes_precedence_over_other_amounts(self):
        result = infer_currency([word('$125.00'),word('EUR')], '336.19 EUR')
        self.assertEqual(result['currency'], 'EUR')
        self.assertTrue(result['conflicting_other_amounts'])

    def test_currency_suggestion_preserves_model_fields_and_warns(self):
        original = {'supplier': 'Example', 'total': '125.00'}
        selected, policy, warnings = apply_currency_evidence(original, [word('$125.00')])
        self.assertEqual(selected, {**original, 'currency': 'USD'})
        self.assertNotIn('currency', original)
        self.assertTrue(warnings)
        self.assertEqual(policy['version'], 'currency-evidence-v1')

    def test_conflict_removes_first_code_guess(self):
        selected, policy, warnings = apply_currency_evidence(
            {'currency': 'USD', 'total': '125.00'}, [word('USD'), word('GBP')])
        self.assertNotIn('currency', selected)
        self.assertTrue(warnings)

    def test_form_normalization_recognizes_symbols_and_rejects_unsupported_guess(self):
        from invoices.extraction import normalize_suggestions
        for total, expected in [('£125.00', 'GBP'), ('＄125.00', 'USD'), ('€125.00', 'EUR')]:
            self.assertEqual(normalize_suggestions({'total': total}), {'total': '125.00', 'currency': expected})
        self.assertNotIn('currency', normalize_suggestions({'total': 'CAD $125.00'}))


if __name__ == '__main__':
    unittest.main()
