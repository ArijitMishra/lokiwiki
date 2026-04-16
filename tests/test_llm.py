from lokiwiki.core.llm import _parse_ingest_response, _parse_query_response
from datetime import datetime

def test_parse_ingest_response_nothing():
    result = _parse_ingest_response("NOTHING", "test.pdf", "2026-04-17")
    assert result["pages"] == []
    assert result["log_entry"] is None

def test_parse_ingest_response_single_page():
    raw = """PAGE_START
filename: Concepts/Attention.md
action: create
title: Attention Mechanism
tags: transformer, attention
related: [[Self-Attention]]

Full content of the page here.
PAGE_END

SUMMARY: Added attention mechanism page."""
    
    result = _parse_ingest_response(raw, "paper.pdf", "2026-04-17")
    assert len(result["pages"]) == 1
    page = result["pages"][0]
    assert page["filename"] == "Concepts/Attention.md"
    assert page["action"] == "create"
    assert page["frontmatter"]["title"] == "Attention Mechanism"
    assert "transformer" in page["frontmatter"]["tags"]
    assert "Full content of the page here." in page["content"]
    assert "Added attention mechanism" in result["log_entry"]

def test_parse_ingest_response_multiple_pages():
    raw = """PAGE_START
filename: Concepts/Attention.md
action: update
title: Attention Mechanism
tags: transformer

Updated body.
PAGE_END

PAGE_START
filename: Sources/Paper.md
action: create
title: The Paper
tags: source

Paper summary.
PAGE_END

SUMMARY: Updated two pages."""
    
    result = _parse_ingest_response(raw, "paper.pdf", "2026-04-17")
    assert len(result["pages"]) == 2
    assert result["pages"][0]["action"] == "update"
    assert result["pages"][1]["filename"] == "Sources/Paper.md"

def test_parse_query_response():
    raw = """ANSWER
The attention mechanism is...
END_ANSWER

SOURCES
Concepts/Attention.md
Sources/Paper.md
END_SOURCES

SAVE_AS
Attention_Explanation.md
END_SAVE_AS"""
    
    result = _parse_query_response(raw)
    assert "attention mechanism" in result["answer"]
    assert result["sources"] == ["Concepts/Attention.md", "Sources/Paper.md"]
    assert result["save_as"] == "Attention_Explanation.md"