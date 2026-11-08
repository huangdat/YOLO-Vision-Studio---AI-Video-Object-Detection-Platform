import json
import logging

from app.config.logging import JsonFormatter


def test_log_message_remains_one_json_record() -> None:
    record = logging.LogRecord(
        "worker.test", logging.INFO, __file__, 1, 'Message with "quotes"\nand newline: %s',
        ("ready",), None,
    )

    rendered = JsonFormatter().format(record)
    payload = json.loads(rendered)

    assert "\n" not in rendered
    assert payload["message"] == 'Message with "quotes"\nand newline: ready'
    assert payload["level"] == "INFO"
    assert payload["logger"] == "worker.test"
    assert payload["timestamp"].endswith("+00:00")
