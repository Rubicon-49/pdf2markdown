# pdf→md — Local PDF → Markdown Converter

Browser-based tool that converts PDFs to Markdown on your local machine.
Supports **4 backends**: Docling · PyMuPDF4LLM · Marker · LlamaParse.

**Target environment:** Ubuntu 24.04 · NVIDIA GPU with 6 GB VRAM · Python 3.13

---

## Project layout

```
pdf2markdown/
├── src/pdf2markdown/
│   ├── app.py          # Flask routes and job management
│   └── converters.py   # All backend conversion logic (no Flask)
├── templates/
│   └── index.html      # Browser UI
├── pyproject.toml
├── Makefile
├── .env                # (you create) — store LLAMA_CLOUD_API_KEY here
├── logs/               # Server logs (auto-created)
├── uploads/            # Temp PDFs (auto-created)
└── outputs/            # Generated .md files (auto-created)
```

---

## Quick start

### 1. Prerequisites

```bash
# Confirm uv is installed
uv --version

# Confirm CUDA is available (optional — only needed for GPU backends)
nvidia-smi
```

### 2. Install dependencies

```bash
make install
```

### 3. Configure API keys (LlamaParse only)

Create a `.env` file in the project root:

```
LLAMA_CLOUD_API_KEY=llx-xxxxxxxxxxxxxxxxxxxxxxxx
```

Get a free key at <https://cloud.llamaindex.ai/> (1 000 pages/day free).
You can also paste the key directly in the browser UI instead.

### 4. Run

```bash
make run
```

Open <http://localhost:5000> in your browser.

---

## Backend guide for 6 GB VRAM

| Backend | VRAM used | Model download | Notes |
|---|---|---|---|
| **PyMuPDF4LLM** | 0 GB | None | Fastest; best for clean text PDFs |
| **Docling** | ~1–2 GB | ~600 MB | Best layout/table quality; auto GPU |
| **Marker** | ~3 GB | ~1.5 GB | Strong OCR; safe on 6 GB (batch_multiplier=1) |
| **LlamaParse** | 0 GB | None | Cloud API; files sent to LlamaIndex |

### Tips for staying within 6 GB

- Don't run Marker and Docling at the same time — models stay in VRAM until the process exits.
- After a heavy conversion, restart the server to fully release VRAM:
  `Ctrl-C` → `make run`

---

## Logging

The server writes structured logs to both stdout and `logs/pdf2markdown.log`
(5 MB rotating, 3 backups). Every job is traceable by its `job_id` prefix.

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
Check your API key at <https://cloud.llamaindex.ai/> and make sure it is
pasted correctly in the UI or set in `.env`.

**Marker: `detectron2` build error**
Install the pre-built wheel:

```bash
pip install detectron2 --extra-index-url https://myhloli.github.io/wheels/
```
