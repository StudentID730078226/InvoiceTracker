# Active application inference: LayoutLM v1

The application worker calls `application_inference.py`. The promoted checkpoint is a copy at `models/layoutlm-v1-invoice`; hashes and selection evidence are in `model_provenance.json`. It is configuration A_baseline, seed 42, epoch 10 from the completed 1500-document study. Configuration and seed selection use development results, not evaluation results. The ongoing augmented1650 study is not deployed.

## Application path

1. Open images as RGB. Render PDF pages at scale 2, or separate tall screenshot pages using pixel evidence.
2. Run docTR OCR on CPU. By default compare CRNN and PARSeq per page using the sum of v1 span confidences; `INVOICE_OCR_ARM=crnn` or `parseq` forces one arm. This is a heuristic, not calibrated probability or guaranteed best OCR.
3. Retry a narrowly anchored invoice-number region when pixel/OCR evidence warrants it; no annotation input is available.
4. Tokenise words with the local LayoutLM v1 tokenizer, maximum 512 tokens and overlap 64. Scale word boxes to 0–1000. Supply text IDs, attention masks, token-type IDs and boxes. **Image pixels are not input to LayoutLM v1**; they are input to OCR.
5. Run `LayoutLMForTokenClassification`, decode B/I/O word labels and select field spans. Report raw predictions separately from evidence-based corrections.
6. Apply the frozen explicit-total-heading selector, existing conservative number/date rules and currency evidence. These are postprocessing, not new model classes.
7. Return JSON. Django normalises dates and amounts, rejects invalid suggestions and displays editable values. Users must confirm before creating/updating invoice fields.

CUDA is the default for application field-model inference; OCR remains on CPU. Set `INVOICE_MODEL_DEVICE=cpu` to use CPU inference. Unavailable CUDA or less than 1 GiB of free GPU memory fails explicitly so the user can retry. A cached-OCR GPU smoke check matched the CPU field predictions; this does not measure full upload latency. Worker timeout is 600 seconds to accommodate CPU/library cold starts; long PDFs may time out and need manual handling.

## Training implementation

The selected weights were trained with a custom PyTorch loop, not Hugging Face Trainer. The actual source is `ml_evaluation/layoutlm_v1_sequential_tuning1500_v1/run.py`: AdamW, encoder LR 1e-5, head LR 5e-5, weight decay .01, batch size 1, fp16 autocast/GradScaler, unweighted token cross entropy, maximum ten epochs and development checks every two epochs. Labels -100 are ignored. GPU training and current CPU app inference are different execution stages.

## Incoming-image contrast and readable stages

Incoming pages now pass through OpenCV CLAHE in `image_enhancement.enhance_contrast`: LAB lightness only, clip limit 1.5, grid 8x8. Original stored files are unchanged. Page size and geometry stay fixed, so normalised OCR boxes retain their meaning. `INVOICE_CONTRAST=none` disables enhancement for a controlled comparison; the default is `clahe`.

This is an application preprocessing update, not a retraining or a change to frozen OCR caches. Historical accuracy results must not be attributed to this new preprocessing without re-evaluation. See `ml_evaluation/layoutlm_v1_clahe_check_v1` for a small paired regression check; it is not a general accuracy benchmark.

Three inspectable stages: `image_enhancement.py` handles contrast, `ocr.py` returns actual words/boxes, and `field_model.py` verifies/loads the trained encoder and classifier and records its real architecture. The loaded model has 12 encoder layers, 12 attention heads, hidden size 768, and a Linear 768-to-11 BIO head. No image pixels are passed to LayoutLM v1. No automatic deskew, perspective correction or 224-pixel invoice resize is applied.

## Preservation

The replaced v3 integration and its selected checkpoint are preserved in the root `lvm 3` folder. Historical v3 experiment directories remain in place because active experiments use frozen historical preparation helpers. New app code imports no LayoutLMv3 model classes. Existing extraction database rows preserve their original model_version; no rows or original results are rewritten.

Validation evidence is stored in `ml_evaluation/layoutlm_v1_app_migration_v1`. The seven cached OCR scan regressions and a fresh OCR smoke check are integration evidence, not an independent production-accuracy benchmark. The added total rule was motivated by previously exposed examples. Model and dataset licensing still need separate consideration for a commercial product.

## Image-level application API

`image_extraction.py` exposes `extract_image(image)` for a PIL page. Its `preprocess_image` calls the separate CLAHE enhancement stage. `lvm_model` is a `LocalInvoiceExtractor` configured with the trained checkpoint; weights/OCR load lazily on the first request. Its `extract` method actually runs OCR, v1 token classification and evidence rules. The CLI `application_inference.main` uses this function per page, then retains document-level span ranking and JSON output. This is a wrapper API, not a claim that LayoutLM directly accepts image pixels.
