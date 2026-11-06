"""Annotation-free page boundaries and invoice-number evidence for OCR."""
import re


def screenshot_page_bounds(image):
    """Split only tall images with full-width, pale grey page-shadow gutters.

    Blank white space and dark printed rules are never page boundaries. Keep
    all content-bearing segments. Ordinary single-page dataset renders stay
    in their original coordinate system.
    """
    import numpy as np
    width, height = image.size
    if height < width * 1.8:
        return [(0, 0, width, height)]
    gray = np.asarray(image.convert('L'), dtype=float)
    rows = gray[:, int(width*.05):int(width*.95)]
    means, spreads = rows.mean(1), rows.std(1)
    shadow = (means >= 225) & (means <= 248) & (spreads < 2)
    groups = []
    start = None
    for i, present in enumerate(list(shadow) + [False]):
        if present and start is None:
            start = i
        elif not present and start is not None:
            if 3 <= i-start <= width*.05:
                groups.append((start, i))
            start = None
    # Require both a document-top shadow and a separate internal gutter. This
    # avoids treating a single grey horizontal strip in a receipt as a break.
    tops = [g for g in groups if g[1] < width*.3 and (rows[:g[0]] < 180).sum() < 20]
    if not tops:
        return [(0, 0, width, height)]
    begin = tops[-1][1]
    cuts = []
    for low, high in groups:
        previous = cuts[-1][1] if cuts else begin
        if low-previous >= width*.5 and height-high >= width*.5:
            if (rows[previous:low] < 180).sum() > 100 and (rows[high:] < 180).sum() > 100:
                cuts.append((low, high))
    if not cuts:
        return [(0, 0, width, height)]
    bounds = []
    for low, high in cuts:
        bounds.append((0, begin, width, low))
        begin = high
    bounds.append((0, begin, width, height))
    return bounds


def _clean(text):
    return text.casefold().strip(' :.#')


def number_heading(words):
    for i, word in enumerate(words):
        label = _clean(word['text'])
        if re.fullmatch(r'invoice\s+(?:number|no|#)', label):
            return word['bbox']
        if label not in {'number', 'no', 'invoice no'} and word['text'] != '#':
            continue
        box = word['bbox']
        for prior in words[max(0, i-3):i]:
            other = prior['bbox']
            if (_clean(prior['text']) == 'invoice' and other[0] <= box[0]
                and box[0]-other[2] < .08
                and abs((box[1]+box[3]-other[1]-other[3])/2) < max(box[3]-box[1],other[3]-other[1])):
                return [other[0], min(box[1],other[1]), box[2], max(box[3],other[3])]
    return None


def number_region(words):
    heading = number_heading(words)
    if not heading:
        return None
    x0,y0,x1,y1 = heading
    return [max(0,x0-.015), max(0,y0-.005), 1, min(1,y1+max(.035,3*(y1-y0)))]


def anchored_number(words):
    heading = number_heading(words)
    region = number_region(words)
    if not region:
        return None
    candidates=[]
    for word in words:
        text = word['text'].strip()
        box = word['bbox']
        cx,cy = (box[0]+box[2])/2,(box[1]+box[3])/2
        below = box[1] >= heading[3]-.002
        beside = box[0] >= heading[2]-.002 and cy >= heading[1]-.002
        if not (region[0]<=cx<=region[2] and region[1]<=cy<=region[3] and (below or beside)):
            continue
        if not re.fullmatch(r'(?=.{1,60}$)(?=.*\d)[A-Za-z0-9][A-Za-z0-9./_-]*',text):
            continue
        if re.fullmatch(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}',text) or re.fullmatch(r'\d{1,2}-[A-Za-z]{3,9}-\d{2,4}',text):
            continue
        if text.isdigit() and any(
            re.fullmatch(r'(?i)January|February|March|April|May|June|July|August|September|October|November|December',other['text'])
            and abs((other['bbox'][1]+other['bbox'][3])/2-cy)<max(box[3]-box[1],other['bbox'][3]-other['bbox'][1])*.65
            for other in words):
            continue
        inline=abs(cy-(heading[1]+heading[3])/2)<=max(box[3]-box[1],heading[3]-heading[1])*.65
        candidates.append((0 if inline else 1,cy,text))
    if not candidates:
        return None
    best_priority=min(c[0] for c in candidates)
    nearest=min(c[1] for c in candidates if c[0]==best_priority)
    values={text for priority,y,text in candidates if priority==best_priority and abs(y-nearest)<(heading[3]-heading[1])*.65}
    return next(iter(values)) if len(values)==1 else None


def retry_number_words(image, words, recognize):
    """One bounded heading-derived retry, returning words in original geometry."""
    region = number_region(words)
    if not region or anchored_number(words):
        return words, {'retried': False, 'anchored_number': anchored_number(words)}
    width,height=image.size
    pixel_box=tuple(round(value*size) for value,size in zip(region,[width,height,width,height]))
    crop=image.crop(pixel_box)
    if min(crop.size)<2:
        return words, {'retried':False,'reason':'empty_region'}
    scale=min(6,max(2,800/crop.width))
    crop=crop.resize((round(crop.width*scale),round(crop.height*scale)))
    additions=[]
    for word in recognize(crop):
        box=word['bbox']
        mapped=[region[0]+box[0]*(region[2]-region[0]), region[1]+box[1]*(region[3]-region[1]),
                region[0]+box[2]*(region[2]-region[0]), region[1]+box[3]*(region[3]-region[1])]
        additions.append({**word,'bbox':mapped})
    # Only accept a unique value supported by the invoice-number heading.
    value=anchored_number(words+additions)
    accepted=[w for w in additions if w['text'].strip()==value] if value else []
    output=list(words)
    if accepted:
        # Insert near the heading's reading order; do not append to unrelated
        # later-page terms or re-sort the existing OCR stream.
        heading=number_heading(words)
        position=max(i for i,w in enumerate(words) if w['bbox'][1]<=heading[3])+1
        output[position:position]=accepted[:1]
    return output, {'retried':True,'region':region,'anchored_number':value,'added_words':len(accepted[:1])}


def has_due_date_heading(words):
    # A bare 'Date' beside a signature, or 'Balance Due', is not a due-date label.
    text=' '.join(w['text'].casefold() for w in words)
    return bool(re.search(r'\b(?:due\s+date|date\s+due|pay\s+by|payment\s+due|due\s+on)\b',text))
