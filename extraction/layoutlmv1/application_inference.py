"""Local docTR OCR → LayoutLM v1 → reviewed field suggestions. No annotation access."""
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from extraction.layoutlmv1.runtime import select_fields
from extraction.layoutlmv1.preprocessing import pages
from extraction.layoutlmv1.image_enhancement import contrast_settings
from extraction.layoutlmv1.total_selection import improve
from extraction.layoutlmv1.field_rules import _refine_fields,_ocr_fallbacks
from invoices.currency import apply_currency_evidence

CHECKPOINT=ROOT/'models/layoutlm-v1-invoice'
MODEL_VERSION='layoutlm-v1-1500-A-seed42-epoch10-evidence2'

def recognize(image, predictor):
    """Compatibility entry point; OCR implementation is separated in ocr.py."""
    from extraction.layoutlmv1.ocr import extract_text
    return extract_text(image, predictor)

def load_model(device, checkpoint=CHECKPOINT):
    """Compatibility entry point for the verified field-model loader."""
    from extraction.layoutlmv1.field_model import load_trained_model
    return load_trained_model(checkpoint, device)

def finish(raw,documents,words):
    """Keep model output separate from heading/currency evidence and warnings."""
    selected,totals=improve(raw,documents)
    for field,value in _ocr_fallbacks(words).items():
        if field not in selected or field in {'currency','invoice_date','due_date'}:selected[field]=value
    selected,warnings=_refine_fields(selected,words)
    selected,currency_policy,currency_warnings=apply_currency_evidence(selected,words)
    if totals['changed']:warnings.append('Total selected beside an explicit invoice-total heading; verify it against the document.')
    return selected,warnings+currency_warnings,{'total':totals,'currency':currency_policy}

def main(source,destination):
    """Run page preparation, OCR, field inference and JSON export for one upload."""
    from extraction.layoutlmv1.image_extraction import extract_image, lvm_model
    began=time.monotonic()
    spans=[];documents=[];all_words=[];trace=[];selected_arms=[]
    # OCR sees pixels; LayoutLM v1 receives only the resulting words and boxes.
    for image,page in pages(source):
        extracted_information=extract_image(image)
        state=extracted_information['page_state']
        chosen,words,found,tokens,number_policy=(state[key] for key in ['ocr_arm','words','spans','tokens','number_retry'])
        spans.extend({**s,'page':page} for s in found)
        documents.append({'page':page,'words':[{'text':w['text'],'bbox_normalized':w['bbox']} for w in words]})
        all_words.extend({**w,'page':page} for w in words);selected_arms.append(chosen)
        trace.append({'page':page,'image_size':image.size,'selected_ocr':chosen,'number_retry':number_policy,'tokens':tokens, 'preprocessing':contrast_settings()})
    if not documents:
        raise ValueError('The document contains no readable pages.')
    # Return reviewable suggestions; this process never writes Invoice records.
    raw=select_fields(spans);selected,warnings,evidence=finish(raw,documents,all_words)
    if not all_words:warnings.append('No text was recognised. Enter invoice details manually.')
    result={'suggestions':selected,'raw_model_suggestions':raw,'warnings':['Machine-generated suggestions require verification.']+warnings,
            'model_version':MODEL_VERSION,'model_device':lvm_model.device,'ocr_device':'cpu','ocr_policy':{'requested':lvm_model.arm,'selected_per_page':selected_arms},
            'preprocessing':{'rgb':True,'pdf_render_scale':2,'screenshot_page_separation':True,'clahe':any(p['preprocessing']['contrast']=='clahe' for p in trace),'contrast_pages':[p['preprocessing'] for p in trace],'automatic_deskew':False},
            'model_architecture':extracted_information.get('model_architecture',{}),'evidence':evidence,'trace':trace,'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),'seconds':time.monotonic()-began}
    path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':main(sys.argv[1],sys.argv[2])
