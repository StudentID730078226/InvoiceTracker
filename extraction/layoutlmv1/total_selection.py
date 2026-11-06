"""Experimental gross-total selection from OCR alone; no reference inputs."""
import re

AMOUNT=re.compile(r'^(?:[$£€]\s*)?\(?-?\d[\d,]*\.\d{2}\)?(?:\s*(?:USD|GBP|EUR))?$',re.I)

def improve(prediction,pages):
    result=dict(prediction); candidates=[]
    for page in pages:
        words=page['words']
        box=lambda w:w.get('bbox_normalized',w.get('bbox'))
        cy=lambda w:(box(w)[1]+box(w)[3])/2
        # Form short headings by geometry, independent of OCR block ordering.
        for first in words:
            text=re.sub(r'[^a-z]','',first['text'].lower())
            if text not in {'total','grand'}:continue
            b=box(first); height=b[3]-b[1]
            nearby=sorted([w for w in words if abs(cy(w)-cy(first))<max(.006,height*.5)
                           and b[0]-.002<=box(w)[0]<=b[2]+.15],key=lambda w:box(w)[0])
            heading=' '.join(w['text'].lower() for w in nearby if not AMOUNT.fullmatch(w['text'].strip()))
            compact=re.sub(r'[^a-z]','',heading)
            if compact.startswith('totalinvoice'):priority=10;reason='explicit total invoice'
            elif compact.startswith('grandtotal'):priority=8;reason='grand total'
            elif compact.startswith('totaldue'):priority=7;reason='explicit total due'
            else:continue
            amounts=[w for w in words if AMOUNT.fullmatch(w['text'].strip())
                     and box(w)[0]>b[2] and abs(cy(w)-cy(first))<max(.007,height*.65)]
            if not amounts:continue
            if reason=='grand total' and len(amounts)>1:
                # Multi-column accounts: only use an explicitly named cumulative column.
                cumulative=[w for w in words if re.sub(r'[^a-z]','',w['text'].lower())=='cumulative'
                            and 0<cy(first)-cy(w)<.30]
                if not cumulative:continue
                amounts=[w for w in amounts if any(abs((box(w)[0]+box(w)[2])/2-(box(c)[0]+box(c)[2])/2)<.07 for c in cumulative)]
            for amount in amounts:
                a=box(amount)
                # Exclude a conditional late-payment row.
                context=[w['text'].lower() for w in words if abs(cy(w)-cy(amount))<.008 and abs(box(w)[0]-a[0])<.35]
                if 'after' in context:continue
                candidates.append({'text':amount['text'],'priority':priority,'reason':reason,
                                   'page':page['page'],'bbox':a})
    if not candidates:return result,{'changed':False,'reason':'no unambiguous strong heading'}
    strongest=max(c['priority'] for c in candidates)
    chosen=[c for c in candidates if c['priority']==strongest]
    values={re.sub(r'[$£€,\s]','',c['text']) for c in chosen}
    if len(values)!=1:return result,{'changed':False,'reason':'conflicting strong totals','candidates':chosen}
    candidate=chosen[0];before=result.get('total');result['total']=candidate['text']
    return result,{'changed':before!=result['total'],'before':before,'after':result['total'],'evidence':candidate}
