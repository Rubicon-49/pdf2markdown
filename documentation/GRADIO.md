# Gradio — how it works in this project

Gradio is a Python library that turns Python functions into web UIs. You describe the layout using Python objects, and Gradio handles rendering the HTML, managing browser events, and calling your Python functions when the user interacts.

This document is structured in three parts:

**Core concepts** explains how Gradio works as a framework.
**This app** explains how those concepts are applied here specifically.
**Reference** covers advanced topics (state, concurrency, deployment) that you only need when extending the app.

---

## Part 1 — Core concepts

### The three building blocks

Every Gradio app is built from three things:

**Components** are widgets — file uploads, radio buttons, text boxes, buttons. Each maps to a Python variable. Input components collect values from the user; output components display values produced by Python.

**Layout containers** arrange components on screen. `gr.Row` places children horizontally, `gr.Column` vertically, `gr.Group` adds a named boundary for CSS targeting. They nest like HTML divs.

**Event handlers** connect user actions to Python functions. When the user clicks Convert, Gradio reads every component in the `inputs` list, calls `convert_pdf()` with those values, and writes the results back to every component in the `outputs` list. The mapping is positional: first input → first argument, first output →
first return value.

---

### How a single interaction flows

```text
Browser                        Gradio Server                  Python handler
  │                                 │                               │
  │── WebSocket: {event, inputs} ──>│                               │
  │                                 │── dispatch to thread ────────>│
  │                                 │                               │ yield 1 ("Starting…")
  │<── WebSocket: {patch outputs} ──│<─────────────────────────────│
  │    log_output = "Starting…"     │                               │
  │                                 │                               │ (conversion runs)
  │                                 │                               │ yield 2 (results)
  │<── WebSocket: {patch outputs} ──│<─────────────────────────────│
  │    log, stats, preview, file    │                               │
```

Three things are worth noting. The browser holds a **persistent WebSocket
connection** — there is no HTTP request per interaction after the initial page
load. Each `yield` produces one WebSocket frame carrying a **patch** — only the
components whose values changed, not a full re-render. And the handler runs in its
own thread, which is why it can block on model inference without stalling other
users.

Everything that follows is an elaboration of one of those steps.

---

### The `gr.Blocks` context manager

```python
with gr.Blocks(title="pdf → markdown") as demo:
    backend = gr.Radio(...)
    convert_btn = gr.Button(...)
```

When the `with` block opens, Gradio pushes the `Blocks` instance onto a
thread-local stack. Every component constructor called inside the block
self-registers with it. When the block closes, Gradio finalizes the component
graph. This is the same pattern TensorFlow uses for `tf.Graph()` — registration
is implicit, you never pass `demo` to each component manually.

The entire `with` block is a **registration phase**. Nothing renders to the
browser at this point — that happens only when `demo.launch()` is called.

A practical consequence: event wiring (`.change()`, `.click()`) must come at the
end of the `with` block, after every component already exists in the graph.

---

### Object identity

The variable name is irrelevant to Gradio. When you pass `backend` as an input to
an event handler, Gradio uses the object's `id()` to look up its current value in
the internal graph. The same object must appear in both the layout and the event
wiring — you cannot recreate a component and expect Gradio to treat it as the same
widget.

---

### Streaming with generator functions

Normal functions return once. Generator functions `yield` multiple times, and
Gradio streams each yield to the browser as a separate update:

```python
def convert_pdf(...):
    yield "Starting…", gr.update(visible=False), None, ...  # immediate feedback
    # ... conversion runs ...
    yield log_text, gr.update(visible=True), word_count, ... # results
```

Each yielded tuple must have exactly the same length as the `outputs` list. The
first yield gives the user immediate feedback before the long-running work begins.

---

### `gr.update()` — patching components from a handler

`gr.update()` modifies a component's properties without replacing it:

```python
gr.update(visible=False)           # hide a component
gr.update(value="new text")        # change its content
gr.update(visible=True, value="")  # show it and clear its content
gr.update()                        # no-op: leave the component unchanged
```

Returning `None` for a `gr.Number` or `gr.Textbox` clears its value. `gr.update()`
with no arguments explicitly leaves it unchanged — useful when a yield touches
only some outputs.

---

### `visible=False` — DOM presence vs screen visibility

Hidden components are rendered into the HTML with `display: none`. They exist in
the DOM, hold state, and can receive updates at any time. Setting
`gr.update(visible=True)` sends a diff over WebSocket — it does not re-render the
surrounding page.

---

### `interactive` — input vs display mode

Every component has an `interactive` parameter controlling whether the user can
edit it. Setting it explicitly removes ambiguity:

```python
log_output = gr.Textbox(interactive=False, ...)  # display only
preview    = gr.Textbox(interactive=False, ...)  # display only
```

A `gr.Textbox` with `interactive=True` renders a `<textarea>` the user can type
into, and its value is sent to handlers as input. With `interactive=False` it is a
styled read-only display. A `gr.Textbox` that looks like output but is
accidentally interactive will send unexpected values to handlers.

---

### Error handling inside handlers

**Yield an error string** (what this app does):

```python
except Exception as exc:
    yield f"❌ Error: {exc}", gr.update(visible=False), None, ...
```

The UI stays functional and the yielded tuple matches the `outputs` list length.
The user can fix their input and try again.

**Raise `gr.Error`** (alternative):

```python
raise gr.Error(f"Conversion failed: {exc}")
```

Gradio displays a red modal banner and interrupts immediately with no partial
updates.

This app uses the yield approach because `convert_pdf` is a generator. Once it has
yielded "Starting…", that update is already in the browser. Raising `gr.Error`
after a partial yield would leave the UI in an inconsistent state.

---

## Part 2 — This app

### Component reference

**Inputs** — values the user provides, passed as arguments to `convert_pdf`:

| Component | Variable | Purpose |
| --- | --- | --- |
| `gr.File` | `pdf_input` | PDF upload dropzone |
| `gr.Radio` | `backend` | Engine selection (2×2 grid) |
| `gr.Checkbox` | `ocr`, `tables`, `device`, `clean` | Toggle switches |
| `gr.Textbox` | `api_key` | LlamaParse API key (password field) |
| `gr.Button` | `convert_btn` | Triggers conversion |

**Outputs** — values written back to the browser after each yield:

| Component | Variable | Purpose |
| --- | --- | --- |
| `gr.HTML` | `header_html` | Dynamic equation header |
| `gr.Markdown` | `backend_info` | Description below engine grid |
| `gr.Textbox` | `log_output` | Scrolling progress log |
| `gr.Row` | `stat_row` | Container for the three stat cards |
| `gr.Number` | `stat_words`, `stat_lines`, `stat_secs` | Post-conversion stats |
| `gr.Textbox` | `preview` | First 3,000 chars of output |
| `gr.File` | `download` | Download link for the `.md` file |

---

### Layout tree

```text
gr.Row                            ← full-width header row
  gr.HTML                         ← the equation header

gr.Row                            ← main two-column row
  gr.Column (left)                ← inputs
    gr.File                       ← PDF upload
    gr.Radio                      ← engine selector
    gr.Markdown                   ← engine description
    gr.Group (options-hardware)   ← GPU toggle
    gr.Group (options-processing) ← OCR + table checkboxes
    gr.Group (options-output)     ← whitespace toggle
    gr.Textbox                    ← API key (hidden by default)
    gr.Button                     ← Convert

  gr.Column (right)               ← outputs
    gr.Textbox                    ← progress log
    gr.Row (stat-row)             ← word / line / second cards
      gr.Number × 3
    gr.Textbox                    ← markdown preview
    gr.File                       ← download link
```

`gr.Group` carries no layout semantics — it is a pure wrapper that gives a set of
components a shared `elem_id` for CSS targeting. `style.css` can then target
`#options-hardware` as a unit for borders and spacing without touching each
checkbox individually.

Layout containers can be assigned to variables with `as`:

```python
with gr.Row(elem_id="stat-row", visible=False) as stat_row:
    ...
```

`stat_row` needs to be a variable so it can appear in the `outputs` list of
`convert_btn.click()` and receive `gr.update(visible=True)` after a successful
conversion.

---

### The two event handlers

**Engine selection** — fires when the user picks a different backend:

```python
backend.change(
    _on_backend_change,
    inputs=backend,
    outputs=[backend_info, ocr, tables, device, api_key, header_html],
)
```

`_on_backend_change` returns six `gr.update()` dicts — one per output. It shows
and hides the checkboxes relevant to the selected backend, updates the info text,
and rebuilds the header HTML with the new engine name.

**Convert button** — fires when the user clicks Convert:

```python
convert_btn.click(
    convert_pdf,
    inputs=[pdf_input, backend, ocr, tables, clean, device, api_key],
    outputs=[log_output, stat_row, stat_words, stat_lines, stat_secs, preview, download],
)
```

`convert_pdf` is a generator. It yields "Starting…" immediately, runs the
conversion, then yields the results. The stat row starts hidden and becomes visible
only on a successful second yield.

---

### Conditional UI via visibility

Rather than tabs or multiple pages, this app shows and hides components based on
the selected engine. All visibility logic lives in `_on_backend_change()`:

| Setting | Visible for |
| --- | --- |
| OCR | docling only |
| Table extraction | docling only |
| Use GPU | docling and marker |
| API key field | llamaparse only |
| Stat row | after any successful conversion |

---

### Dynamic header HTML

The equation header (`PDF (doc) ──[docling]──→ .md (clean)`) rebuilds as an HTML
string every time the engine changes. `_build_header_html(backend)` injects the
selected backend name into an f-string of inline HTML, which `gr.HTML` renders
verbatim:

```python
def _build_header_html(backend: str = "docling") -> str:
    return f"""
    <div style="...">
      <span class="eq-catalyst">{backend}</span>
      ...
    </div>
    """
```

Inline `style=""` attributes are used rather than CSS classes so this HTML is
unaffected by Gradio's style conflicts. The CSS classes (`.eq-catalyst`, etc.) are
defined in `style.css` and apply to the rendered output.

---

### `_build_runner` — conditional decoration

`_build_runner` is a factory that produces two variants of the conversion runner
at module load time:

```python
_gpu_runner = _build_runner(gpu=True)
_cpu_runner = _build_runner(gpu=False)
```

Inside the factory, `_run` holds the real logic. On Hugging Face Spaces the GPU
variant is wrapped with `spaces.GPU`; locally it is returned as-is:

```python
def _build_runner(gpu: bool):
    def _run(pdf_path_str, options):
        ...                        # real logic, written once

    if gpu and HF_SPACES and spaces is not None:
        return spaces.GPU(_run)    # equivalent to @spaces.GPU
    return _run
```

`spaces.GPU(_run)` is exactly equivalent to `@spaces.GPU` — a decorator is a
function that takes a function and returns a wrapped version. The factory applies
it manually so it can branch on three runtime conditions (`gpu`, `HF_SPACES`,
`spaces is not None`) and produce both variants without duplicating `_run`'s body.

---

### Styling — `elem_id`, `elem_classes`, and `!important`

`elem_id` adds an HTML `id` to a component's outermost wrapper div:

```python
gr.Textbox(elem_id="log-output")
# → <div id="log-output">...</div>
# → CSS: #log-output textarea { ... }
```

`elem_classes` adds a CSS class, useful for styling multiple components at once:

```python
gr.Radio(elem_classes=["engine-grid"])
```

Gradio's built-in styles are loaded after custom CSS and use high-specificity
selectors. `style.css` uses `!important` throughout to win the cascade — this is
intentional. The `THEME` object sets global defaults that flow through all
components; `style.css` handles everything the theme system cannot reach. See
[STYLING.md](STYLING.md) for the full breakdown.

---

## Part 3 — Reference

### Per-session state with `gr.State`

`gr.State` holds a value private to one user session. Each browser tab gets its
own isolated copy — there is no sharing between users:

```python
history = gr.State(value=[])

def add_entry(new_item, current_history):
    return current_history + [new_item]

btn.click(add_entry, inputs=[item_box, history], outputs=history)
```

This app does not currently use `gr.State` because `convert_pdf` is stateless —
every call produces its own output with no dependency on previous calls. If the
app were extended to accumulate a conversion history, `gr.State` would be the
right tool. A module-level Python variable is not a safe alternative: it is shared
across all users and all threads.

---

### Queuing and concurrency

By default Gradio allows only one active request per event handler at a time.
Enabling the queue allows multiple users to convert simultaneously:

```python
demo.queue()
demo.launch(theme=THEME, css=CUSTOM_CSS)
```

`demo.queue()` must be called before `demo.launch()`. It buffers incoming requests
and dispatches them to worker threads, giving each waiting user a live position
indicator. For fine-grained control:

```python
convert_btn.click(convert_pdf, ..., concurrency_limit=2)
```

Gradio runs each handler in a separate thread from a pool — not in an async event
loop. Handlers can use blocking I/O and model inference without stalling other
users. The generator in `convert_pdf` runs in its own thread; each `yield` sends a
WebSocket frame to that specific user's browser connection.

---

### Uploaded file lifecycle

When a user uploads a file, Gradio copies it into a session-scoped temporary
directory and passes the copy's path to the handler:

```python
def convert_pdf(pdf_file: str | None, ...):
    # pdf_file ≈ /tmp/gradio/abc123/upload/document.pdf
```

That path is valid only while the session is active. This is why conversion output
is written to `PROJECT_ROOT / "outputs"` rather than alongside the input — writing
there escapes the temp lifecycle. The resulting path is then passed as the value of
the `gr.File` download component, which serves it to the browser.

`file_types=[".pdf"]` is a client-side filter only — the browser's file picker
restricts what the user can select, but nothing prevents a crafted request from
sending any file. Content validation must happen in the handler itself.

---

### Deployment

**Local development:**

```python
demo.queue()
demo.launch(
    theme=THEME,
    css=CUSTOM_CSS,
    server_name="0.0.0.0",  # listen on all interfaces (default: 127.0.0.1)
    server_port=7860,        # default Gradio port
    share=True,              # create a public gradio.live tunnel
    show_error=True,         # print tracebacks in the browser
)
```

**Hugging Face Spaces:** `launch()` is called with no arguments — Spaces injects
its own `server_name` and `server_port` via environment variables. The `theme` and
`css` arguments are still respected as they are processed before the server starts.

Spaces discovers the app by looking for a `demo` variable at module level in
`app.py`. The `app.py` in the project root imports and re-exports `demo` from
`gradio_app.py` — the logic lives in `gradio_app.py` but Spaces finds it through
`app.py`.
