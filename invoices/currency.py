"""Currency evidence policy shared by the application inference pipeline."""
import re
import unicodedata

SUPPORTED = {'GBP', 'USD', 'EUR'}
CODE = re.compile(r'(?<![A-Z])(GBP|USD|EUR|CAD|AUD|NZD|SGD|HKD)(?![A-Z])', re.I)

POLICY_VERSION = 'currency-evidence-v1'


def markers(text):
    text = unicodedata.normalize('NFKC', text)
    codes = {code.upper() for code in CODE.findall(text)}
    if '£' in text:
        codes.add('GBP')
    if '€' in text:
        codes.add('EUR')
    if '$' in text:
        # The existing app assumes USD. Preserve it only as an explicit,
        # review-required assumption when no qualified dollar code exists.
        if not codes.intersection({'CAD', 'AUD', 'NZD', 'SGD', 'HKD'}):
            codes.add('USD')
    return codes


def infer_currency(words, selected_total=''):
    """Use total evidence first; otherwise require consistent document evidence.

    Only symbols in numeric tokens or next to an amount on the same line count.
    Do not guess £ from E/L or $ from S, and do not use supplier/country priors.
    """
    evidence = []
    for i, word in enumerate(words):
        text = word['text']
        codes = markers(text)
        explicit = bool(CODE.search(text))
        amount = bool(re.search(r'\d', text))
        if not amount and not explicit:
            box = word['bbox']
            for neighbor in words[max(0, i-2):i+3]:
                other = neighbor['bbox']
                if (word.get('page', 0) == neighbor.get('page', 0)
                    and re.search(r'\d', neighbor['text'])
                    and abs((box[1]+box[3]-other[1]-other[3])/2)
                        <= max(box[3]-box[1], other[3]-other[1])*.65
                    and max(0, max(box[0], other[0])-min(box[2], other[2])) < .04):
                    amount = True
        if codes and (explicit or amount):
            evidence.append({'text': text, 'currencies': sorted(codes)})
    total_codes = markers(selected_total)
    all_codes = set().union(*(set(item['currencies']) for item in evidence), total_codes)
    if len(total_codes) == 1 and next(iter(total_codes)) in SUPPORTED:
        currency = next(iter(total_codes))
        return {'currency': currency, 'reason': 'total_marker',
                'conflicting_other_amounts': bool(all_codes - total_codes),
                'dollar_assumption': currency == 'USD' and 'USD' not in selected_total.upper(),
                'evidence': evidence}
    if len(all_codes) > 1:
        return {'currency': None, 'reason': 'conflicting_currency_evidence', 'evidence': evidence}
    if not all_codes:
        return {'currency': None, 'reason': 'no_currency_evidence', 'evidence': evidence}
    currency = next(iter(all_codes))
    if currency not in SUPPORTED:
        return {'currency': None, 'reason': 'unsupported_currency', 'evidence': evidence}
    return {'currency': currency, 'reason': 'total_marker' if total_codes else 'ocr_marker',
            'dollar_assumption': currency == 'USD' and not any(
                'USD' in item['text'].upper() for item in evidence) and 'USD' not in selected_total.upper(),
            'evidence': evidence}


def apply_currency_evidence(suggestions, words):
    """Return review suggestions, provenance and warnings without saving fields."""
    selected = dict(suggestions)
    decision = infer_currency(words, selected.get('total', ''))
    selected.pop('currency', None)
    if decision['currency']:
        selected['currency'] = decision['currency']
    warnings = []
    if decision.get('dollar_assumption'):
        warnings.append('A dollar sign was read as USD. Check the currency; $ can represent other dollars.')
    if decision.get('conflicting_other_amounts'):
        warnings.append('Other amounts show different currencies. The suggestion uses the selected total; verify it.')
    if decision['reason'] == 'conflicting_currency_evidence':
        warnings.append('Different currencies were detected. Select the invoice currency manually.')
    if decision['reason'] == 'unsupported_currency':
        warnings.append('The detected currency is not supported. Check the invoice currency manually.')
    return selected, {'version': POLICY_VERSION, **decision}, warnings
