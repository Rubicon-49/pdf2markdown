# Converters — PDF processing backends

This document explains how `converters.py` works and what each conversion engine does, why it exists, and when to use it.

---

## Structure

`converters.py` has a simple shape:

```bash
_clean_whitespace()       — post-processing helper
convert_docling()         — backend 1
convert_pymupdf4llm()     — backend 2
convert_marker()          — backend 3
convert_llamaparse()      — backend 4
BACKENDS dict             — name → function mapping
DOCUMENT_TYPE_PRESETS     — preset option combinations
run_conversion()          — dispatcher: picks backend, runs it, post-processes
```

The UI only ever calls `run_conversion()`. It never calls a backend function directly.

---

## `run_conversion()` — the dispatcher

```python
def run_conversion(pdf_path: Path, options: dict, log: Callable) -> str:
```

This is the single entry point called from `gradio_app.py`. It:

1. Applies a document-type preset if `options["document_type"]` is set (UI choices always win over preset defaults)
2. Looks up the backend function from the `BACKENDS` dict using `options["backend"]`
3. Calls that function with `(pdf_path, options, log)`
4. Optionally runs `_clean_whitespace()` on the result
5. Returns the final Markdown string

The `log` argument is a callable — specifically `logs.append` from a list in `gradio_app.py`. Every time a backend calls `log("some message")`, that string is appended to the list, which Gradio streams to the progress log in the browser.

---

## `_clean_whitespace()`

A simple regex that collapses three or more consecutive blank lines down to two. All backends tend to produce verbose whitespace around headings and list items. This runs as a post-processing step when `options["clean_whitespace"]` is `True` (the default).

---

## The four backends

### 1. `convert_docling()` — layout analysis

**What it is:** Docling is an IBM Research open-source library for document understanding. It runs a pipeline of ML models that analyse the page layout, detect reading order, identify table structure, and export the result to Markdown.

**How it works:**

- Loads a layout detection model (~600 MB, downloaded once to a local cache on first run)
- Classifies every region on the page: text block, table, figure, title, list, etc.
- Reconstructs reading order across multi-column layouts
- If `ocr=True`, runs EasyOCR (English models) on image-based regions
- Exports the structured document to Markdown

**Key options:**

- `ocr` — enables EasyOCR for image regions. Off by default because it is slow and unnecessary for native digital PDFs
- `tables` — enables table structure detection. On by default
- `device` — `"gpu"` uses CUDA if available, `"cpu"` forces CPU

**When to use it:** Digital PDFs with tables, multi-column layouts, or mixed content. The strongest local option for structured documents.

**When not to use it:** Fully scanned/photographed PDFs where the entire page is a raster image — Docling's layout model classifies the whole page as a `Picture` element and outputs `<!-- image -->`. Use Marker for those.

---

### 2. `convert_pymupdf4llm()` — text layer extraction

**What it is:** PyMuPDF4LLM is a thin wrapper around PyMuPDF (which wraps MuPDF, a C PDF rendering engine). It reads the PDF's embedded text layer directly — no ML models, no OCR.

**How it works:**

- Opens the PDF with MuPDF
- Extracts the text layer: the actual character data embedded in the PDF by the application that created it
- Identifies headings via font size comparisons
- Detects table-like structures by spatial positioning of text blocks
- Returns Markdown

**Key options:** None. This backend ignores `ocr`, `tables`, and `device` — it does not use any of them. The `options` argument is accepted for interface consistency only.

**When to use it:** Fast digital PDFs with straightforward layouts — reports, articles, contracts. The fastest backend by a large margin (no model loading, pure C rendering).

**When not to use it:** Scanned PDFs (no text layer to extract), complex multi-column layouts (reading order may be wrong), or PDFs with important table structure (table detection is heuristic only).

---

### 3. `convert_marker()` — vision-based OCR

**What it is:** Marker is a PDF-to-Markdown converter built on Surya, a suite of ML models for document understanding. Unlike Docling, it treats the page primarily as a visual object rather than as a structured document with a text layer.

**How it works:**

- Rasterises each PDF page to an image
- Runs a layout detection model to identify regions
- Runs OCR (Surya's own recognition model) on text regions
- Reconstructs reading order
- Returns Markdown

**Key options:**

- `device` — `"gpu"` or `"cpu"`. GPU is strongly recommended; CPU is very slow for Marker
- `batch_multiplier=0.5` — hardcoded in the function to keep VRAM usage within ~3 GB on a 6 GB card. Default batch sizes use the full 3 GB

**VRAM note:** Marker loads ~1.5 GB of models on first run and keeps them in VRAM. Running Marker immediately after Docling (which also loads models) can cause OOM errors on 6 GB cards. Restart the server between heavy jobs if needed.

**`PYTORCH_ALLOC_CONF=expandable_segments:True`** is set automatically to reduce memory fragmentation, which can prevent OOM on borderline cases.

**When to use it:** Scanned or photographed PDFs where the page is a raster image, not a text-layer PDF. Also good for complex academic papers and visually dense layouts.

**When not to use it:** Clean digital PDFs — PyMuPDF4LLM will be 10–100× faster and equally accurate.

---

### 4. `convert_llamaparse()` — cloud LLM parsing

**What it is:** LlamaParse is a cloud API from LlamaIndex that uses a large language model to parse PDFs. The PDF is uploaded to their servers, processed, and the result is returned.

**How it works:**

- Opens the PDF file in binary mode
- Uploads it to the LlamaCloud API using the `llama_cloud` Python client
- Polls for the result (handled internally by the client)
- Returns the `markdown_full` field from the response

**Authentication:** Requires a `LLAMA_CLOUD_API_KEY`. The function checks `options["llamaparse_api_key"]` first, then falls back to the `LLAMA_CLOUD_API_KEY` environment variable. Raises `ValueError` with a clear message if neither is set.

**Key options:** None meaningful. `device` and `ocr` are ignored — all processing happens in the cloud.

**Privacy note:** Your PDF is sent to LlamaIndex's servers. Do not use this backend for confidential documents.

**Free tier:** 1,000 pages per day at the time of writing.

**When to use it:** PDFs that other backends fail on — unusual layouts, mixed languages, complex tables in scanned documents. The most capable option but the only one with a privacy tradeoff.

---

## Document type presets

`DOCUMENT_TYPE_PRESETS` is a dict of option combinations that pre-configure sensible defaults for known document types. The UI currently always uses `"general"` (no preset), but the infrastructure is in place to expose this in the UI later.

```python
DOCUMENT_TYPE_PRESETS = {
    "exercise_page":      {"backend": "llamaparse", "ocr": True,  "tables": True,  "clean_whitespace": True},
    "financial_report":   {"backend": "pymupdf4llm", "ocr": False, "tables": True,  "clean_whitespace": False},
    "scanned_document":   {"backend": "marker",      "ocr": True,  "tables": True,  "clean_whitespace": True},
    "general":            {},   # no overrides — user choices apply
}
```

Presets are defaults, not overrides. If the user has explicitly set an option in the UI, that value wins:

```python
options = {**preset, **options}   # UI choices overwrite preset values
```

---

## Adding a new backend

1. Write a function with the signature `convert_xyz(pdf_path: Path, options: dict, log: Callable) -> str`
2. Add it to the `BACKENDS` dict: `"xyz": convert_xyz`
3. Add a description to `_BACKEND_INFO` in `gradio_app.py`
4. Add a radio choice in the `backend = gr.Radio(choices=[...])` definition
5. Update `_on_backend_change()` if the new backend needs its own visibility logic for checkboxes

The dispatcher in `run_conversion()` requires no changes — it picks up the new backend automatically from `BACKENDS`.
