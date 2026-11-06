import unittest
from PIL import Image, ImageDraw
from invoices.document_evidence import (screenshot_page_bounds, retry_number_words,
                                        anchored_number, has_due_date_heading)
from invoices.extraction import normalize_suggestions


def word(text,box):return {'text':text,'bbox':box}


class DocumentEvidenceTests(unittest.TestCase):
    def test_uk_numeric_hyphen_date_is_accepted(self):
        self.assertEqual(normalize_suggestions({'invoice_date':'04-11-2026'})['invoice_date'],'2026-11-04')

    def test_unambiguous_us_hyphen_date_remains_readable(self):
        self.assertEqual(normalize_suggestions({'invoice_date':'11-23-2020'})['invoice_date'],'2020-11-23')

    def test_whitespace_in_tall_image_is_not_page_boundary(self):
        image=Image.new('RGB',(400,1000),'white')
        self.assertEqual(screenshot_page_bounds(image),[(0,0,400,1000)])

    def test_page_shadow_split_retains_both_content_regions(self):
        image=Image.new('RGB',(400,1100),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((0,40,399,46),fill=(239,239,239))
        draw.rectangle((0,650,399,660),fill=(239,239,239))
        draw.rectangle((50,100,180,120),fill='black')
        draw.rectangle((50,800,180,820),fill='black')
        self.assertEqual(screenshot_page_bounds(image),[(0,47,400,650),(0,661,400,1100)])

    def test_one_digit_number_with_heading_outranks_phone_evidence(self):
        words=[word('07707456853',[.8,.1,.92,.12]),word('Invoice',[.76,.2,.83,.22]),
               word('number',[.84,.2,.93,.22]),word('3',[.9,.23,.92,.25])]
        self.assertEqual(anchored_number(words),'3')

    def test_retry_requires_heading_and_unique_value(self):
        words=[word('Invoice',[.76,.2,.83,.22]),word('number',[.84,.2,.93,.22])]
        # Recognizer crop geometry maps the value below the heading.
        additions=[word('3',[.65,.7,.7,.9])]
        revised,policy=retry_number_words(Image.new('RGB',(1000,2000),'white'),words,lambda _:additions)
        self.assertTrue(policy['retried'])
        self.assertEqual(anchored_number(revised),'3')
        unlabelled=[word('3',[.9,.23,.92,.25])]
        revised,policy=retry_number_words(Image.new('RGB',(100,100),'white'),unlabelled,lambda _:self.fail('Unexpected retry'))
        self.assertFalse(policy['retried'])

    def test_inline_identifier_beats_day_on_next_row(self):
        words=[word('Invoice',[.06,.16,.12,.18]),word('number:',[.13,.16,.25,.18]),
               word('RE-2026-0442',[.30,.16,.50,.18]),word('14',[.30,.20,.32,.22]),
               word('January',[.34,.20,.42,.22]),word('2026',[.44,.20,.51,.22])]
        self.assertEqual(anchored_number(words),'RE-2026-0442')

    def test_signature_or_balance_due_is_not_due_date_heading(self):
        self.assertFalse(has_due_date_heading([word('Balance',[0,0,0,0]),word('Due:',[0,0,0,0]),word('Date:',[0,0,0,0])]))
        self.assertTrue(has_due_date_heading([word('Due',[0,0,0,0]),word('date',[0,0,0,0])]))
