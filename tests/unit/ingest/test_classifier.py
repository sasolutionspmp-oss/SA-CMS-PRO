from app.ingest.classifier import (
    classify_section,
    classify_text,
    detect_addendum,
    detect_revision,
)


def test_classify_text_matches_disciplines() -> None:
    text = "Mechanical drawing for pump room"
    assert classify_text(text) == "MEP"


def test_classify_text_no_match_returns_none() -> None:
    assert classify_text("General instructions") is None


def test_detect_revision_handles_alphanumeric() -> None:
    assert detect_revision("See REV B2 for updates") == "B2"


def test_detect_addendum_extracts_token() -> None:
    assert detect_addendum("Refer to Addendum 5 for clarifications") == "5"


def test_classify_section_detects_instructions_to_bidders() -> None:
    text = "Instructions to Bidders: submit sealed proposals to the purchasing office by 2:00 PM. Bid security in the amount of five percent is required."
    assert classify_section(text) == "instructions_to_bidders"


def test_classify_section_detects_specifications_and_filename_hint() -> None:
    text = (
        "SECTION 07 21 00 - THERMAL INSULATION\n"
        "PART 1 - GENERAL\n"
        "This section covers insulation materials."
    )
    assert (
        classify_section(text, filename="docs/specification-072100.txt")
        == "specifications"
    )


def test_classify_section_returns_none_for_ambiguous_text() -> None:
    assert classify_section("Meeting notes and general discussion") is None


def test_classifier_sample_corpus_covers_major_sections() -> None:
    samples: list[tuple[str, str, str | None]] = [
        (
            "Instructions to Bidders must submit sealed proposals by 2 PM. Bid security is required for each bid.",
            "docs/itb.pdf",
            "instructions_to_bidders",
        ),
        (
            "General Conditions of the Contract for Construction reference AIA A201 and supplementary conditions herein.",
            "docs/general_conditions.pdf",
            "general_conditions",
        ),
        (
            "SECTION 07 21 00 - THERMAL INSULATION\nPART 1 - GENERAL\nPart 2 - Products detail materials.",
            "specs/072100.txt",
            "specifications",
        ),
        (
            "Plan view of Level 2 showing north arrow, elevation markers, and drawing number A-201.",
            "plans/A201.pdf",
            "plans",
        ),
        (
            "Project schedule milestone timeline includes Phase 1 start, week 4 turnover, and month 6 substantial completion.",
            "schedules/master_schedule.xlsx",
            "schedules",
        ),
        (
            "Addendum No. 2 clarifies door hardware sets and includes updated bulletins for finishes.",
            "addenda/Addendum02.pdf",
            "addenda",
        ),
        (
            "Construction safety plan aligns with OSHA requirements and details personal protective equipment (PPE).",
            "safety/site_safety_plan.docx",
            "safety_requirements",
        ),
        (
            "Provide performance bond and payment bond certificates naming the owner as additional insured.",
            "legal/bonding.pdf",
            "bonds_and_insurance",
        ),
        (
            "Complete the bid form including unit price schedule, alternate bid amounts, and allowance breakdowns.",
            "forms/bid_form.pdf",
            "pricing_forms",
        ),
        (
            "Weekly coordination meeting notes and general discussion of punch list items.",
            "docs/meeting_notes.txt",
            None,
        ),
        (
            "Scope of Work summary outlines project scope, major systems, and work includes demo and build back.",
            "scope/scope_summary.txt",
            "scope_of_work",
        ),
    ]

    hits = 0
    for text, filename, expected in samples:
        result = classify_section(text, filename=filename)
        if expected is None:
            assert result is None
        else:
            assert result == expected
            hits += 1
    assert hits / len(samples) >= 0.9
