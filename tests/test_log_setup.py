import logging
import logging.handlers

from pdf2markdown.log_setup import setup_logging


def test_setup_logging_adds_stream_and_file_handlers(tmp_path):
    # Use a fresh named logger so the idempotency guard doesn't block setup.
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
