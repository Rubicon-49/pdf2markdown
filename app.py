"""app.py — local entry point.

Runs the FastAPI app with uvicorn on http://localhost:7860.
"""

import uvicorn


def main() -> None:
    uvicorn.run(
        "pdf2markdown.web_app:app",
        host="0.0.0.0",
        port=7860,
        reload=False,
    )


if __name__ == "__main__":
    main()
