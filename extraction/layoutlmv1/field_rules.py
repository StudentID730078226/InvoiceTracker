"""Shared conservative application evidence rules, migrated from the v3 adapter."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from datetime import datetime
from invoices.currency import infer_currency
from invoices.document_evidence import anchored_number, has_due_date_heading

def _valid_total(text):
    value=unicodedata.normalize('NFKC',text)
    value=re.sub(r'(?i)\b(?:GBP|USD|EUR)\b|[$£€]', '', value).replace(',','').strip()
    try:
        amount=Decimal(value)
        return amount.is_finite() and amount>=0
    except InvalidOperation:
        return False

def _refine_fields(selected, words):
    selected=dict(selected)
    warnings=[]
    numbers={anchored_number([w for w in words if w.get('page',0)==page])
             for page in {w.get('page',0) for w in words}}
    numbers.discard(None)
    number=next(iter(numbers)) if len(numbers)==1 else None
    if number and not selected.get('invoice_number'):
        selected['invoice_number']=number
        warnings.append('Invoice number was recovered beside its printed heading; verify it.')
    elif number and number!=selected.get('invoice_number'):
        warnings.append('The printed invoice-number heading suggests a different value. Check the invoice number against the document.')
    if selected.get('due_date') and not has_due_date_heading(words):
        value=selected['due_date'].strip()
        signature_date=any(
            word['text'].strip()==value and
            any(re.fullmatch(r'(?i)(?:signed|signature|signed by)\s*:?',other['text'])
                and other.get('page',0)==word.get('page',0)
                and 0<=word['bbox'][0]-other['bbox'][2]<.65
                and abs(sum(word['bbox'][1::2])/2-sum(other['bbox'][1::2])/2)
                    <=max(word['bbox'][3]-word['bbox'][1],other['bbox'][3]-other['bbox'][1])*.75
                for other in words)
            for word in words)
        if signature_date:
            selected.pop('due_date')
            warnings.append('A signature date was omitted as a due date. Enter a due date only if the invoice states one.')
        else:
            warnings.append('No explicit due-date heading was read. Check the suggested due date against the invoice.')
    for field in ['invoice_date','due_date']:
        value=selected.get(field,'')
        match=re.fullmatch(r'(\d{1,2})-(\d{1,2})-(\d{4})',value)
        if match and 1<=int(match[1])<=12 and 1<=int(match[2])<=12 and match[1]!=match[2]:
            warnings.append('Numeric dates with hyphens use day-month-year. Check the invoice date format.')
            break
    return selected,warnings

def _bbox_union(words):
    return [
        min(word["bbox"][0] for word in words),
        min(word["bbox"][1] for word in words),
        max(word["bbox"][2] for word in words),
        max(word["bbox"][3] for word in words),
    ]

def _ocr_fallbacks(words):
    """Recover values whose BIO labels are absent or only partially tagged."""
    values = {}
    currency = infer_currency(words)
    if currency['currency']:
        values['currency'] = currency['currency']

    date_candidates = []
    month = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    for index in range(len(words) - 2):
        match = re.fullmatch(r"([0-3]?\d)", words[index]["text"])
        if not match or not re.fullmatch(month, words[index + 1]["text"], re.IGNORECASE):
            continue
        year = re.fullmatch(r"(20\d{2})", words[index + 2]["text"])
        if not year:
            continue
        try:
            parsed = datetime.strptime(
                f"{match.group(1)} {words[index + 1]['text']} {year.group(1)}",
                "%d %B %Y",
            )
        except ValueError:
            continue
        candidate_words = words[index:index + 3]
        date_candidates.append((_bbox_union(candidate_words), parsed.strftime("%Y-%m-%d")))

    headings = {}
    for word in words:
        label = word["text"].lower().rstrip(":")
        if label in {"invoice", "due"}:
            headings[label] = word["bbox"]
    for field, heading in (("invoice_date", "invoice"), ("due_date", "due")):
        if field in values or heading not in headings or not date_candidates:
            continue
        hx = (headings[heading][0] + headings[heading][2]) / 2
        hy = (headings[heading][1] + headings[heading][3]) / 2
        _, value = min(
            date_candidates,
            key=lambda item: abs(((item[0][0] + item[0][2]) / 2) - hx)
            + abs(((item[0][1] + item[0][3]) / 2) - hy),
        )
        values[field] = value
    invoice_number = re.compile(r"(?i)^[A-Z]{1,6}-\d{2,4}-[A-Z0-9-]+$")
    number_words = [word["text"] for word in words if invoice_number.fullmatch(word["text"])]
    if number_words:
        values["invoice_number"] = number_words[0]
    return values
