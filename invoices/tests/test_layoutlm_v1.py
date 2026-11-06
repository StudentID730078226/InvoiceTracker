"""Application migration guards; inference rules have no annotation inputs."""
from pathlib import Path
from unittest import TestCase
from django.conf import settings
from extraction.layoutlmv1.application_inference import MODEL_VERSION,finish
from extraction.layoutlmv1.runtime import select_fields
from django.test import TestCase as DjangoTestCase, override_settings
from unittest.mock import patch
import tempfile
import json

def word(text,box):return {'text':text,'bbox':box,'page':0}

class LayoutLMV1IntegrationTests(TestCase):
    def test_checkpoint_loader_verifies_then_delegates_to_matching_components(self):
        import hashlib
        from extraction.layoutlmv1.field_model import load_trained_model
        with tempfile.TemporaryDirectory() as folder:
            checkpoint=Path(folder);payload=b'fixture weights'
            (checkpoint/'weights.bin').write_bytes(payload)
            provenance={'files':{'weights.bin':hashlib.sha256(payload).hexdigest()}}
            tokenizer=object();model=object()
            with patch('extraction.layoutlmv1.field_model.json.loads',return_value=provenance), \
                 patch('extraction.layoutlmv1.field_model.load_invoice_tokenizer',return_value=tokenizer) as token_loader, \
                 patch('extraction.layoutlmv1.field_model.load_invoice_model',return_value=model) as model_loader:
                self.assertEqual(load_trained_model(checkpoint,'cpu'),(tokenizer,model))
                token_loader.assert_called_once_with(checkpoint)
                model_loader.assert_called_once_with(checkpoint,'cpu')
                (checkpoint/'weights.bin').write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'provenance mismatch'):
                    load_trained_model(checkpoint,'cpu')
                self.assertEqual(token_loader.call_count,1)
                self.assertEqual(model_loader.call_count,1)

    def test_image_entry_point_passes_image_and_returns_adapter_result(self):
        from extraction.layoutlmv1.image_extraction import extract_image
        image=object()
        prepared=object()
        expected={'suggestions':{'supplier':'Example'}}
        with patch('extraction.layoutlmv1.image_extraction.lvm_model') as adapter, \
             patch('extraction.layoutlmv1.image_extraction.preprocess_image',return_value=prepared) as preprocessing:
            adapter.extract.return_value=expected
            self.assertIs(extract_image(image),expected)
            preprocessing.assert_called_once_with(image)
            adapter.extract.assert_called_once_with(prepared)

    def test_clahe_preserves_page_geometry_and_original_pixels(self):
        import numpy as np
        from PIL import Image
        from extraction.layoutlmv1.image_enhancement import enhance_contrast
        pixels=np.tile(np.linspace(110,140,64,dtype=np.uint8),(64,1))
        image=Image.fromarray(pixels)
        with patch.dict('os.environ',{'INVOICE_CONTRAST':'clahe'}):result=enhance_contrast(image)
        self.assertEqual(result.size,image.size)
        self.assertEqual(result.mode,'RGB')
        self.assertTrue(np.array_equal(np.asarray(image),pixels))
        self.assertFalse(np.array_equal(np.asarray(result.convert('L')),pixels))

    def test_contrast_can_be_disabled_for_comparison(self):
        from PIL import Image
        from extraction.layoutlmv1.image_enhancement import enhance_contrast
        image=Image.new('RGB',(32,40),(120,130,140))
        with patch.dict('os.environ',{'INVOICE_CONTRAST':'none'}):result=enhance_contrast(image)
        self.assertEqual(result.tobytes(),image.tobytes())

    def test_ocr_returns_real_word_boxes_and_ignores_blank_tokens(self):
        from PIL import Image
        from extraction.layoutlmv1.ocr import extract_text
        fake=type('Output',(),{'export':lambda self:{'pages':[{'blocks':[{'lines':[{'words':[
            {'value':'Invoice','geometry':((.1,.2),(.3,.4)),'confidence':.9},
            {'value':' ','geometry':((0,0),(1,1)),'confidence':.1}]}]}]}]}})()
        with patch('torch.inference_mode'):
            predictor=lambda images:fake
            result=extract_text(Image.new('RGB',(20,20)),predictor)
        self.assertEqual(result,[{'text':'Invoice','bbox':[.1,.2,.3,.4],'ocr_confidence':.9}])

    def test_document_worker_uses_image_entry_point_and_preserves_page_ranking(self):
        import tempfile
        from types import SimpleNamespace
        from PIL import Image
        from extraction.layoutlmv1.application_inference import main
        image=Image.new('RGB',(20,20),'white')
        def page(amount,score):
            return {'page_state':{'ocr_arm':'parseq','words':[{'text':amount,'bbox':[.1,.1,.2,.2]}],
                'spans':[{'field':'total','text':amount,'score':score}],
                'tokens':[],'number_retry':{}}}
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.png';image.save(source)
            with patch('extraction.layoutlmv1.application_inference.pages',return_value=[(image,0),(image,1)]), \
                 patch('extraction.layoutlmv1.image_extraction.extract_image',side_effect=[page('100.00',.4),page('200.00',.9)]) as extract, \
                 patch('extraction.layoutlmv1.image_extraction.lvm_model',SimpleNamespace(device='cpu',arm='combined')):
                result=main(source,Path(folder)/'result.json')
            self.assertEqual(extract.call_count,2)
            self.assertEqual(result['suggestions']['total'],'200.00')
            self.assertEqual([p['page'] for p in result['trace']],[0,1])

    def test_both_worker_routes_target_v1(self):
        source=(Path(settings.BASE_DIR)/'invoices/extraction.py').read_text(encoding='utf-8')
        self.assertEqual(source.count('extraction/layoutlmv1/application_inference.py'),2)
        self.assertNotIn('ml/layoutlmv3/scripts/application_inference.py',source)
        self.assertIn('layoutlm-v1-',MODEL_VERSION)

    def test_total_invoice_heading_replaces_contract_amount(self):
        words=[word('TOTAL',[.1,.4,.17,.42]),word('INVOICE',[.18,.4,.28,.42]),word('119,750.00',[.5,.4,.65,.42])]
        pages=[{'page':0,'words':[{'text':w['text'],'bbox_normalized':w['bbox']} for w in words]}]
        fields,warnings,policy=finish({'supplier':'Example','total':'479,000.00'},pages,words)
        self.assertEqual(fields['total'],'119,750.00')
        self.assertEqual(fields['supplier'],'Example')
        self.assertTrue(policy['total']['changed'])

    def test_ambiguous_heading_does_not_choose_largest_amount(self):
        words=[word('Amount',[.1,.4,.2,.42]),word('100.00',[.5,.4,.6,.42]),word('900.00',[.5,.6,.6,.62])]
        pages=[{'page':0,'words':[{'text':w['text'],'bbox_normalized':w['bbox']} for w in words]}]
        fields,_,_=finish({'total':'100.00'},pages,words)
        self.assertEqual(fields['total'],'100.00')

    def test_highest_scored_span_retained_without_reference_boxes(self):
        result=select_fields([{'field':'supplier','text':'A','score':.4},{'field':'supplier','text':'B','score':.9}])
        self.assertEqual(result,{'supplier':'B'})

class WorkerContractTests(DjangoTestCase):
    def test_pending_worker_runs_v1_and_persists_validated_result(self):
        from django.contrib.auth import get_user_model
        from accounts.models import Business,Membership
        from invoices.pending import stage_upload
        from invoices.extraction import process_pending_run,INFERENCE_TIMEOUT_SECONDS
        from invoices.tests.test_workflow import image_upload
        user=get_user_model().objects.create_user('v1-contract')
        business=Business.objects.create(name='V1 contract')
        Membership.objects.create(user=user,business=business,role='client')
        with tempfile.TemporaryDirectory() as media,override_settings(MEDIA_ROOT=media):
            pending=stage_upload(user,business.pk,image_upload())
            pending.status='queued';pending.save(update_fields=['status'])
            def result(command,**kwargs):
                self.assertTrue(str(command[1]).replace('\\','/').endswith('extraction/layoutlmv1/application_inference.py'))
                self.assertEqual(kwargs['timeout'],INFERENCE_TIMEOUT_SECONDS)
                Path(command[-1]).write_text(json.dumps({'suggestions':{'supplier':'Example','invoice_number':'123',
                    'invoice_date':'05/27/18','total':'$170.00'},'model_version':MODEL_VERSION,'warnings':[]}))
            with patch('invoices.extraction.subprocess.run',side_effect=result):process_pending_run(pending.pk)
            pending.refresh_from_db()
            self.assertEqual(pending.status,'succeeded')
            self.assertEqual(pending.model_version,MODEL_VERSION)
            self.assertEqual(pending.suggestions['total'],'170.00')
            self.assertEqual(pending.suggestions['invoice_date'],'2018-05-27')
