# Testing

This document explains the test suite: how to run it, what each file covers, and the techniques used — particularly for readers unfamiliar with `pytest` or `unittest.mock`. Concepts are explained at the point of first use rather than upfront, so you can read just the section for the file you are working in.

---

## Running the tests

```bash
make test           # run the full suite
make check          # lint + typecheck + test in one step
```

Or directly with pytest:

```bash
pytest                           # all tests
pytest tests/test_converters.py  # one file
pytest -v                        # verbose — shows each test name and result
pytest -x                        # stop on first failure
```

---

## File overview

| File | Module tested | What it covers |
| --- | --- | --- |
| `test_converters.py` | `converters.py` | Whitespace helper, backend dispatch, log forwarding, LlamaParse API call |
| `test_gradio_app.py` | `gradio_app.py` | UI visibility logic, header HTML, conversion generator (success, error, no-file) |
| `test_log_setup.py` | `log_setup.py` | Correct handler types are registered |
| `test_utils.py` | `utils.py` | Project root discovery, walk-up logic, error case |

---

## 1. `test_converters.py`

This file tests the conversion layer in isolation. No browser, no Gradio, no real PDF processing — just the dispatch logic, the whitespace helper, and the LlamaParse API call.

### 1.1 Shared helper: `_noop_log`

Every backend function requires a `log` callable. Most tests do not care what gets logged, so a silent discard function is defined once at module level:

```python
def _noop_log(msg: str) -> None:
    """No-op log callable; avoids repeating ``lambda msg: None`` in tests."""
```

Defining it as a named function rather than a repeated `lambda msg: None` makes test signatures cleaner and the intent explicit.

---

### 1.2 `_clean_whitespace` — five boundary tests

These tests cover the edge cases of the single regex `re.sub(r"\n{3,}", "\n\n", text)`. Each test is one assertion — no setup needed, no mocking.

| Test name | Input | Expected | What it pins down |
| --- | --- | --- | --- |
| `collapses_newlines` | `"line1\n\n\n\nline2"` | `"line1\n\nline2"` | 4 newlines → 2 |
| `leaves_double_newline` | `"line1\n\nline2"` | `"line1\n\nline2"` | 2 newlines untouched |
| `collapses_trailing_newlines` | `"a\n\n\n"` | `"a\n\n"` | trailing run at end of string |
| `empty_string` | `""` | `""` | empty input survives |
| `exactly_two_newlines` | `"a\n\nb"` | `"a\n\nb"` | boundary at exactly 2 |

The last two overlap with `leaves_double_newline` in terms of code coverage, but they document the contract at its boundary values explicitly.

---

### 1.3 `run_conversion` — dispatch, log forwarding, and whitespace

**`tmp_path` — isolated temporary directories**

Several tests need a real file on disk to pass as a `pdf_path`. `tmp_path` is a built-in pytest fixture — a value pytest creates and injects automatically when a test declares it as a parameter:

```python
def test_something(tmp_path: Path):
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")   # empty file, just needs to exist
```

Each test gets a fresh temporary directory that is deleted automatically afterward. Tests that write files never conflict with each other.

**`patch.dict` — replacing backend functions without loading ML models**

The real backends (docling, marker, etc.) require hundreds of MB of model weights to be installed. Tests replace them with lightweight fakes using `patch.dict`:

```python
mock_fn = MagicMock(return_value="markdown")

with patch.dict("pdf2markdown.converters.BACKENDS", {"docling": mock_fn}):
    run_conversion(pdf_path, {"backend": "docling", "clean_whitespace": False}, _noop_log)

mock_fn.assert_called_once()
```

`patch.dict` temporarily replaces entries in the `BACKENDS` dictionary for the duration of the `with` block. When the block exits, the original dict is restored. The string `"pdf2markdown.converters.BACKENDS"` is the fully qualified path to the dict: the `BACKENDS` name inside the `converters` module inside the `pdf2markdown` package.

`MagicMock` is an object that accepts any attribute access or method call and returns another `MagicMock`. Passing `return_value="markdown"` makes it return that string when called as a function. `assert_called_once()` confirms the mock was called exactly once.

**`@pytest.mark.parametrize` — one test function, four backends**

The dispatch test runs once per backend without duplicating the function:

```python
def test_run_conversion_dispatches_to_correct_backend(
    tmp_path: Path,
    backend: Literal["docling", "pymupdf4llm", "marker", "llamaparse"],
):
    ...
```

This produces four separate test cases reported individually. If `marker` fails but `docling` passes, both results appear in the output.

**Log forwarding** — uses a plain list instead of a mock. The fake backend calls `log("hello from backend")`. The test appends to `received` via `received.append` and confirms the message arrived after passing through `run_conversion`'s internal `_log` wrapper:

```python
received = []
with patch.dict("pdf2markdown.converters.BACKENDS", {"docling": fake_backend}):
    run_conversion(pdf_path, {"backend": "docling", "clean_whitespace": False}, _noop_log)

assert any("hello from backend" in msg for msg in received)
```

**Unknown backend** — does not patch `BACKENDS`, so `"nonexistent"` genuinely
is not in it. Uses `pytest.raises` to assert both the exception type and that the
error message names the unknown backend:

```python
with pytest.raises(ValueError, match="nonexistent"):
    run_conversion(pdf_path, {"backend": "nonexistent"}, _noop_log)
```

The `match=` argument is a regex matched against the exception message. The test
fails if no exception is raised, or if the wrong type is raised.

**Whitespace toggle** — injects a lambda backend that returns a string with four
newlines. Two tests use the same lambda, one with `clean_whitespace=True` and one
with `False`, asserting presence or absence of collapsing.

---

### `convert_llamaparse` — verifying the full API call chain

This is the most layered test in the file. It patches `LlamaCloud` itself rather than the `BACKENDS` dict, because the goal is to verify the exact arguments the function passes to the cloud client — not just that it calls something.

```python
mock_result = MagicMock()
mock_result.markdown_full = "# Hello"     # configure a specific attribute

mock_client = MagicMock()
mock_client.parsing.parse.return_value = mock_result   # chain of attribute access

with patch("llama_cloud.LlamaCloud", return_value=mock_client) as mock_cls:
    result = convert_llamaparse(pdf_path, {"llamaparse_api_key": "llx-testkey"}, _noop_log)
```

`patch` replaces `llama_cloud.LlamaCloud` with a `MagicMock` for the duration of the block. `return_value=mock_client` means `LlamaCloud(api_key=...)` returns `mock_client` rather than a real object. `as mock_cls` captures the mock so assertions can be made on how it was constructed.

After the call, three things are asserted:

```python
mock_cls.assert_called_once_with(api_key="llx-testkey")   # correct key passed
mock_client.parsing.parse.assert_called_once_with(        # correct API arguments
    upload_file=ANY,
    tier="fast",
    version="latest",
    expand=["markdown_full"],
    verbose=False,
)
assert result == "# Hello"                                 # correct return value
```

`ANY` (from `unittest.mock`) matches any value — used for `upload_file` because the exact file handle object is not worth pinning down and would make the test fragile.

---

## `test_gradio_app.py`

This file tests the UI layer — visibility logic, header content, and the
conversion generator — without starting a browser or a Gradio server. Gradio
components can be imported and their functions called directly in Python.

### Visibility tests — asserting `gr.update()` dicts

`_on_backend_change(backend)` returns a 6-tuple of `gr.update()` dicts. Each dict
has a `"visible"` key. The tests unpack the tuple positionally and check the right
pattern of `True`/`False` per backend:

| Backend | `ocr` | `tables` | `device` | `api_key` |
| --- | --- | --- | --- | --- |
| `docling` | True | True | True | False |
| `marker` | False | False | True | False |
| `pymupdf4llm` | False | False | False | False |
| `llamaparse` | False | False | False | True |

A separate parametrized test confirms the info text is also updated:

```python
@pytest.mark.parametrize("backend", list(_BACKEND_INFO))
def test_on_backend_change_updates_info_text(backend):
    info, *_ = _on_backend_change(backend)
    assert info["value"] == _BACKEND_INFO[backend]
```

`*_` discards the remaining 5 elements of the tuple — only `info` is needed. The
test is parametrized over `_BACKEND_INFO`'s keys, so any new backend added to that
dict is automatically covered without touching the test.

The header test is a smoke test only — it confirms the HTML string contains the
backend name and the equation terms (`"PDF"` and `".md"`), without parsing HTML
structure, which would make it brittle.

---

### Generator tests — the conversion pipeline

`convert_pdf` is a generator. `list(convert_pdf(...))` exhausts it and collects
all yielded tuples, letting the tests assert on every yield in a single call.

**Why `pymupdf4llm` is used as the test backend**

`pymupdf4llm` is CPU-only, so `convert_pdf` always selects `_cpu_runner` for it.
This makes the patch target predictable — only `_cpu_runner` needs to be patched,
not both runners:

```python
_CPU_RUNNER = "pdf2markdown.gradio_app._cpu_runner"

with patch(_CPU_RUNNER, return_value=(_MOCK_MARKDOWN, _MOCK_LOGS)):
    results = list(convert_pdf(str(pdf_path), "pymupdf4llm", ...))
```

**No-file guard** — passes `None` as the PDF path. Expects exactly one yield
containing a warning with all stats `None` and the stat row hidden:

```python
log, stat_row_update, words, lines, secs, preview, download = results[0]
assert "No file" in log
assert stat_row_update["visible"] is False
```

**Starting message** — calls `next(gen)` to consume only the first yield, without
waiting for the conversion to finish. Confirms the function yields immediately,
which is what gives the user instant feedback before the work begins.

**Success path** — patches `_cpu_runner` to return instantly. Checks the second
yield carries the correct word count, line count, a float for seconds, a preview,
a path ending in `.md`, and that `stat_row_update["visible"] is True`.

**Exception path** — uses `side_effect` instead of `return_value`:

```python
with patch(_CPU_RUNNER, side_effect=RuntimeError("backend exploded")):
    results = list(convert_pdf(...))
```

`side_effect` tells the mock to raise an exception when called rather than return
a value. The test confirms the second yield contains the error message, hides the
stat row, and sets all numeric outputs to `None`.

---

## `test_log_setup.py`

A single test that confirms `setup_logging()` registers both a stream handler
(stdout) and a rotating file handler:

```python
def test_setup_logging_adds_stream_and_file_handlers(tmp_path):
    app_logger = logging.getLogger("pdf2markdown")
    original_handlers = app_logger.handlers[:]
    app_logger.handlers.clear()

    try:
        setup_logging(tmp_path)
        handler_types = {type(h) for h in app_logger.handlers}
        assert logging.StreamHandler in handler_types
        assert logging.handlers.RotatingFileHandler in handler_types
    finally:
        for h in app_logger.handlers:
            h.close()
        app_logger.handlers[:] = original_handlers
```

**Why `try/finally`**: Python's logging module is global state. Handlers left
attached after a test would interfere with other tests or leak open file handles.
`finally` guarantees cleanup even if the assertions fail.

**Why `original_handlers[:]`**: this is a shallow copy of the list, not a
reference to it. Restoring `app_logger.handlers[:] = original_handlers` puts the
original handlers back in place rather than replacing the list object itself, which
would break Gradio's internal reference to the same list.

**Why clear first**: `setup_logging` has an idempotency guard — it does nothing if
handlers are already registered. Clearing first ensures the function actually runs
and its registration can be observed.

---

## `test_utils.py`

Three tests for `find_project_root()`, which walks up the directory tree from an
anchor file looking for `pyproject.toml`.

**Basic** — calls `find_project_root()` with no argument, which defaults to the
location of `utils.py` itself. Asserts `pyproject.toml` exists in the returned
path. This test depends on the actual project structure, so it would fail if
`pyproject.toml` were deleted or moved.

**Nested anchor** — passes a path deep inside the project tree and confirms the
same root is returned. Exercises the walk-up loop for a file that is not directly
adjacent to `pyproject.toml`.

**Error case** — creates a temporary directory tree with no `pyproject.toml`
anywhere in its ancestry, then confirms `FileNotFoundError` is raised with a
message mentioning `pyproject.toml`. Uses `tmp_path` to guarantee the directory
genuinely has no `pyproject.toml` above it:

```python
def test_find_project_root_raises_when_no_pyproject(tmp_path):
    anchor = tmp_path / "no_project_here" / "file.py"
    anchor.parent.mkdir()
    anchor.write_text("")
    with pytest.raises(FileNotFoundError, match="pyproject.toml"):
        find_project_root(anchor)
```

---

## What is not tested

The following are explicitly out of scope and would require integration tests with
real PDFs and dependencies installed:

- `convert_docling`, `convert_pymupdf4llm`, `convert_marker` — require their
  respective ML libraries and model weights
- GPU allocation via `spaces.GPU` — requires a Hugging Face Spaces environment
- The Gradio UI rendering itself — Gradio does not provide a headless test client

To test the real backends, run the app locally and upload a PDF, or write
integration tests in a CI environment that installs the full dependency set.
