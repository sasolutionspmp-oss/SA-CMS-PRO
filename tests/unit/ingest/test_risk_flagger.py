from app.ingest.risk_flagger import RiskFlag, detect_risk_flags


def _flag_codes(flags: list[RiskFlag]) -> set[str]:
    return {flag.code for flag in flags}


def test_detect_risk_flags_returns_expected_codes() -> None:
    text = (
        "Liquidated damages of $500 per day apply to this contract.\n"
        "Bid bond equal to five percent is required before award.\n"
        "No substitutions will be accepted after approval.\n"
        "Provide warranty coverage for a 10-year period on roofing systems."
    )

    flags = detect_risk_flags(text)
    codes = _flag_codes(flags)

    assert "liquidated_damages" in codes
    assert "bonding" in codes
    assert "no_substitutions" in codes
    assert "warranty_anomaly" in codes

    line_map = {flag.code: flag.line for flag in flags}
    assert line_map["liquidated_damages"] == 1
    assert line_map["bonding"] == 2
    assert line_map["no_substitutions"] == 3
    assert line_map["warranty_anomaly"] == 4


def test_detect_risk_flags_deduplicates() -> None:
    text = "Liquidated damages apply. Liquidated damages apply."
    flags = detect_risk_flags(text)
    assert len(flags) == 1
    assert flags[0].code == "liquidated_damages"
