from app.ingest.normalizer import normalize_chunks, sanitize_text


def test_normalize_chunks_respects_bounds() -> None:
    text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit." * 80
    chunks = normalize_chunks(text, min_chars=1500, max_chars=2000)
    assert chunks, "expected chunks to be generated"
    if len(chunks) == 1:
        assert len(chunks[0].text) <= 2000
    else:
        for chunk in chunks[:-1]:
            assert 1500 <= len(chunk.text) <= 2000
        assert len(chunks[-1].text) <= 2000
        assert len(chunks[-1].text) >= 300
    reconstructed = " ".join(chunk.text for chunk in chunks)
    assert "  " not in reconstructed


def test_sanitize_text_redacts_contacts() -> None:
    text = "Contact us at Email@example.com or (555) 123-4567."
    sanitized, redacted = sanitize_text(text, redact=True)
    assert sanitized == "Contact us at [REDACTED_EMAIL] or [REDACTED_PHONE]."
    assert redacted is True

    collapsed, collapsed_flag = sanitize_text("Line one\n\nLine two", redact=False)
    assert collapsed == "Line one\nLine two"
    assert collapsed_flag is False
