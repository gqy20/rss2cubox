from rss2cubox import enrich_agent


def test_enrich_schema_requires_structured_signal_fields() -> None:
    schema = enrich_agent.ENRICH_OUTPUT_SCHEMA
    properties = schema["properties"]
    required = set(schema["required"])

    expected = {
        "content_source",
        "signal_type",
        "evidence_type",
        "evidence_strength",
        "novelty_score",
        "impact_horizon",
        "audience",
        "market_stage",
        "confidence",
        "entities",
        "cluster_hint",
        "watch_keywords",
        "prediction",
        "disconfirming_evidence",
    }

    assert expected.issubset(properties)
    assert expected.issubset(required)


def test_enrich_schema_uses_numeric_codes_for_filterable_fields() -> None:
    properties = enrich_agent.ENRICH_OUTPUT_SCHEMA["properties"]

    assert properties["signal_type"] == {"type": "integer", "minimum": 1, "maximum": 12}
    assert properties["evidence_type"] == {"type": "integer", "minimum": 1, "maximum": 12}
    assert properties["evidence_strength"] == {"type": "integer", "minimum": 1, "maximum": 5}
    assert properties["novelty_score"] == {"type": "integer", "minimum": 1, "maximum": 5}
    assert properties["impact_horizon"] == {"type": "integer", "minimum": 1, "maximum": 5}
    assert properties["market_stage"] == {"type": "integer", "minimum": 1, "maximum": 6}
    assert properties["confidence"] == {"type": "integer", "minimum": 1, "maximum": 5}
    assert properties["audience"]["type"] == "array"
    assert properties["audience"]["items"] == {"type": "integer", "minimum": 1, "maximum": 8}
