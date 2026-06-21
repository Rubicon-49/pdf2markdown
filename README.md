# PDF → Markdown Converter

Browser-based tool that converts PDFs to Markdown.
Supports **4 backends**: Docling · PyMuPDF4LLM · Marker · LlamaParse.

Multi-page PDFs are split into single-page PDFs, converted page-by-page,
and merged back into one downloadable Markdown file. Per-page progress is
streamed live to the browser via Server-Sent Events.

**Target environment:** Ubuntu 24.04 · NVIDIA GPU with 6 GB VRAM · Python 3.13

---

## Stack

- **Backend:** FastAPI + uvicorn
- **Frontend:** Server-rendered Jinja templates + HTMX (+ a sliver of vanilla JS for SSE)
- **PDF I/O:** PyMuPDF (split / page count)
- **Conversion:** see *Backend reference* below

---

## Project layout

```bash
pdf2markdown/
├── app.py                        # uvicorn entry point
├── src/pdf2markdown/
│   ├── web_app.py                # FastAPI app, routes, SSE
│   ├── pdf_pipeline.py           # split → convert each → merge
│   ├── converters.py             # per-backend conversion logic
│   ├── log_setup.py              # rotating file logger
│   ├── utils.py                  # find_project_root
│   ├── templates/                # Jinja templates
│   │   ├── index.html
│   │   ├── _result.html
│   │   └── _backend_info.html
│   └── static/style.css          # dark theme
├── tests/
├── pyproject.toml
├── Makefile
├── .env                          # (you create) — store LLAMA_CLOUD_API_KEY here
├── logs/                         # server logs (auto-created)
├── uploads/                      # temp PDFs + per-page splits (auto-created)
└── outputs/                      # generated .md files (auto-created)
```

---

## Quick start

### 1. Prerequisites

```bash
uv --version    # confirm uv is installed
nvidia-smi      # confirm CUDA is available (optional — GPU backends only)
```

### 2. Install dependencies

```bash
make install
```

### 3. Configure API keys (LlamaParse only)

Create a `.env` file in the project root:

```bash
LLAMA_CLOUD_API_KEY=llx-xxxxxxxxxxxxxxxxxxxxxxxx
```

Get a free key at <https://cloud.llamaindex.ai/> (1,000 pages/day free).
You can also paste the key directly in the browser UI.

### 4. Run

```bash
make run
```

Open <http://localhost:7860> in your browser.

---

## How conversion works

1. The user uploads a PDF and picks a backend.
2. `POST /convert` saves the file, queues a background job, returns a `job_id`.
3. The browser opens an `EventSource` on `/events/{job_id}`.
4. The worker calls `convert_pdf_pages(...)`:
   - If the PDF has one page → convert whole.
   - Otherwise → split into single-page PDFs with PyMuPDF, then run the
     selected backend on each one in order.
5. Per-page `page` events update the progress bar; a final `done` event
   triggers the browser to fetch `/preview/{job_id}` (HTMX swap) and
   exposes the `Download .md` button which hits `/download/{job_id}`.

The merged Markdown joins each page with `\n\n---\n\n` (a Markdown
horizontal rule).

---

## Backend reference

| Backend         | VRAM         | Model download | Best for                         |
| --------------- | ------------ | -------------- | -------------------------------- |
| **PyMuPDF4LLM** | 0 GB         | None           | Fast digital PDFs, clean text    |
| **Docling**     | ~1–2 GB      | ~600 MB        | Tables, columns, complex layouts |
| **Marker**      | ~3 GB        | ~1.5 GB        | Scanned or photographed pages    |
| **LlamaParse**  | 0 GB (cloud) | None           | Difficult layouts, any PDF type  |

### VRAM tips for 6 GB cards

- Don't run Marker and Docling in the same session — models stay in VRAM until the process exits.
- After a heavy Marker conversion, restart the server: `Ctrl-C` → `make run`
- Marker's `batch_multiplier` is pinned to `0.5` to stay within 3 GB.

---

## Logging

The server writes structured logs to both stdout and `logs/pdf2markdown.log`
(5 MB rotating, 3 backups).

---

## Development

```bash
make lint       # Ruff linting
make format     # Auto-fix + format
make typecheck  # mypy static type checking
make test       # pytest
make check      # lint + typecheck + test
```

---

## Troubleshooting

**`ImportError: No module named 'docling'`**
Run `make install` to ensure all dependencies are installed.

**LlamaParse: `401 Unauthorized`**
Check your API key at <https://cloud.llamaindex.ai/> and ensure it is set
in `.env` or pasted in the UI.

**Marker: `CUDA out of memory`**
The PDF may be high-resolution. Try switching to CPU, or reduce the input
resolution by pre-processing the PDF with `pdftoppm` at 150 DPI before
uploading.

**Docling: `<!-- image -->` in output**
The PDF is image-based (scanned/photographed). Enable OCR in the options
panel, or switch to Marker which handles image-based pages natively.
