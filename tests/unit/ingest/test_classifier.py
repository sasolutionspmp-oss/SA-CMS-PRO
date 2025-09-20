from app.ingest.classifier import classify_text, detect_addendum, detect_revision


def test_classify_text_matches_disciplines() -> None:
    text = "Mechanical drawing for pump room"
    assert classify_text(text) == "MEP"


def test_classify_text_no_match_returns_none() -> None:
    assert classify_text("General instructions") is None


def test_detect_revision_handles_alphanumeric() -> None:
    assert detect_revision("See REV B2 for updates") == "B2"


def test_detect_addendum_extracts_token() -> None:
    assert detect_addendum("Refer to Addendum 5 for clarifications") == "5"
