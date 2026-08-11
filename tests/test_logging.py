import logging

from vision_mcp.logging_setup import RedactingFilter


def test_log_filter_redacts_credentials_and_images():
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "Authorization: Bearer ordinary-secret api_key=sk-123456789 data:image/png;base64,AAAA", (), None)
    assert RedactingFilter().filter(record)
    message = record.getMessage()
    assert "ordinary-secret" not in message
    assert "sk-123456789" not in message
    assert "AAAA" not in message


def test_log_filter_redacts_video_payloads():
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "data:video/mp4;base64,QUJDREVGRw==", (), None)
    assert RedactingFilter().filter(record)
    assert "QUJDREVGRw" not in record.getMessage()
