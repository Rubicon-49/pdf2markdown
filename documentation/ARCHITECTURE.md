# Architecture

This document explains how the application is structured and how the pieces fit together. No prior knowledge of Gradio or PDF processing is assumed.

---

## What the app does

A user uploads a PDF. The app passes it through one of four conversion engines and returns a Markdown file. That is the entire purpose — there is no database, no user accounts, no background jobs.

---

## File map

```bash
src/pdf2markdown/
├── gradio_app.py   ← UI definition and event wiring
├── converters.py   ← All conversion logic, one function per engine
├── style.css       ← Custom dark-theme CSS injected into Gradio
└── log_setup.py    ← Rotating file logger (not documented here)
```

---

## Data flow

```bash
Browser
  │
  │  user uploads PDF, picks engine, clicks Convert
  ▼
gradio_app.py — convert_pdf()
  │
  │  calls run_conversion(pdf_path, options, log)
  ▼
converters.py — run_conversion()
  │
  │  looks up the right backend function and calls it
  ▼
converters.py — convert_docling() / convert_pymupdf4llm()
              / convert_marker()  / convert_llamaparse()
  │
  │  returns a Markdown string
  ▼
converters.py — _clean_whitespace()   (optional post-processing)
  │
  ▼
gradio_app.py — yields result back to UI
  │
  ▼
Browser — shows preview, enables download
```

---

## The two main modules

### `gradio_app.py` — UI layer

Responsible for everything the user sees and interacts with. It does not contain any PDF processing logic. Its jobs are:

- Define the layout using Gradio components (`gr.File`, `gr.Radio`, `gr.Textbox`, etc.)
- Wire user interactions to Python functions via `.change()` and `.click()` event handlers
- Call `run_conversion()` from `converters.py` and stream results back to the UI
- Build the dynamic header HTML that updates when the engine selection changes

See [GRADIO.md](GRADIO.md) for a detailed explanation of how Gradio works.

### `converters.py` — conversion layer

Responsible for all PDF processing. It knows nothing about the UI. Its jobs are:

- Provide one function per engine: `convert_docling`, `convert_pymupdf4llm`, `convert_marker`, `convert_llamaparse`
- Provide a `run_conversion()` dispatcher that picks the right function based on `options["backend"]`
- Apply optional post-processing (whitespace normalisation)
- Apply document-type presets that pre-configure sensible option combinations

See [CONVERTERS.md](CONVERTERS.md) for a detailed explanation of each engine.

---

## Options dict

The UI and converters communicate through a plain Python dict called `options`. It is built in `convert_pdf()` and passed unchanged to `run_conversion()`:

```python
options = {
    "backend":           "docling",     # which engine to use
    "ocr":               False,         # enable OCR (docling only)
    "tables":            True,          # enable table extraction (docling only)
    "clean_whitespace":  True,          # collapse blank lines in output
    "device":            "gpu",         # "gpu" or "cpu"
    "llamaparse_api_key": None,         # cloud API key (llamaparse only)
    "document_type":     "general",     # optional preset override
}
```

Keys that are irrelevant to the selected backend are simply ignored by that backend's function.

---

## ZeroGPU (Hugging Face Spaces)

When deployed on Hugging Face Spaces with the ZeroGPU runtime, GPU-heavy backends (docling and marker) need to be wrapped with `@spaces.GPU` so the platform allocates a GPU for the duration of that call and releases it afterward.

The `_build_runner()` function handles this transparently: locally it returns the raw function, on HF Spaces it wraps it with `spaces.GPU`. The rest of the code does not need to know which environment it is running in.

```python
runner = _gpu_runner if backend in GPU_BACKENDS else _cpu_runner
```

`GPU_BACKENDS = {"docling", "marker"}` — pymupdf4llm is CPU-only by design, and llamaparse runs in the cloud.
