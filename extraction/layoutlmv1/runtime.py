"""LayoutLM v1 word/box encoding and BIO decoding; no annotations or pixel model input."""
LABELS=['O']+[f'{prefix}-{field}' for field in ['supplier','invoice_number','invoice_date','due_date','total'] for prefix in ['B','I']]

def encode(words,tokenizer,stride=64):
    """Create 512-token windows, repeating 64 tokens to retain boundary context."""
    encoded=tokenizer([w['text'] for w in words],is_split_into_words=True,truncation=True,max_length=512,stride=stride,
                      return_overflowing_tokens=True,return_offsets_mapping=True,padding='max_length')
    for n,ids in enumerate(encoded['input_ids']):
        # Map subtokens back to OCR words so text and spatial inputs stay aligned.
        word_ids=encoded.word_ids(batch_index=n)
        boxes=[]
        for wid in word_ids:
            box=words[wid].get('bbox_normalized',words[wid].get('bbox')) if wid is not None else [0,0,0,0]
            # LayoutLM expects integer box coordinates in its 0–1000 layout grid.
            boxes.append([min(1000,max(0,round(v*1000))) for v in box])
        yield {'input_ids':ids,'attention_mask':encoded['attention_mask'][n],
               'token_type_ids':encoded.get('token_type_ids',[[0]*len(ids)]*len(encoded['input_ids']))[n],
               'bbox':boxes,'word_ids':word_ids,'offsets':encoded['offset_mapping'][n]}

def predict_page(words,tokenizer,model,device):
    """Classify first subtokens and decode word-level BIO spans, without labels."""
    import torch
    owned={}
    if not words:return [],[]
    for window in encode(words,tokenizer):
        features={key:torch.tensor([window[key]],dtype=torch.long,device=device) for key in ['input_ids','attention_mask','token_type_ids','bbox']}
        # A forward pass returns class logits; softmax supports span ranking.
        with torch.inference_mode():probabilities=model(**features).logits.softmax(-1)[0]
        for i,wid in enumerate(window['word_ids']):
            if wid is None or window['offsets'][i][0]!=0:continue
            label=int(probabilities[i].argmax());confidence=float(probabilities[i,label])
            # Overlapping windows may predict the same word: retain one result.
            if wid not in owned or confidence>owned[wid][1]:owned[wid]=(label,confidence)
    spans=[];current=None;tokens=[]
    # O ends a span; B starts a field value; compatible I tokens continue it.
    for i,word in enumerate(words):
        label,confidence=owned.get(i,(0,0));name=LABELS[label]
        tokens.append({'text':word['text'],'bbox':word.get('bbox_normalized',word.get('bbox')),'label':name,'confidence':confidence})
        if name=='O':current=None;continue
        prefix,field=name.split('-',1)
        if prefix=='B' or current is None or current['field']!=field:
            current={'field':field,'words':[],'scores':[]};spans.append(current)
        current['words'].append(word['text']);current['scores'].append(confidence)
    return [{'field':s['field'],'text':' '.join(s['words']),'score':sum(s['scores'])/len(s['scores'])} for s in spans],tokens

def select_fields(spans):
    """Keep the highest-ranked candidate for each field across the document."""
    result={}
    for span in sorted(spans,key=lambda s:-s['score']):result.setdefault(span['field'],span['text'])
    return result
