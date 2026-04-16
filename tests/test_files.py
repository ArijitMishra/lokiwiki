from lokiwiki.core.files import (
    read_source, read_source_by_pages, copy_to_raw,
    load_index, update_index, append_log,
    lint_wiki, get_all_wiki_pages
)
from pathlib import Path
import pytest

def test_read_source_txt(temp_vault):
    src = temp_vault / "raw" / "test.txt"
    src.write_text("Hello world", encoding="utf-8")
    text, name = read_source(str(src))
    assert text == "Hello world"
    assert name == "test.txt"

def test_read_source_pdf(mock_pdf, temp_vault):
    src = temp_vault / "raw" / "test.pdf"
    src.touch()
    text, name = read_source(str(src))
    assert "page 1 text" in text
    assert "page 2 text" in text
    assert name == "test.pdf"


def test_read_source_by_pages_pdf(mock_pdf, temp_vault):
    src = temp_vault / "raw" / "test.pdf"
    src.touch()
    pages, name = read_source_by_pages(str(src))
    assert len(pages) == 2
    assert "page 1 text" in pages[0]
    assert "page 2 text" in pages[1]
    assert name == "test.pdf"


def test_read_source_by_pages_txt(temp_vault):
    src = temp_vault / "raw" / "test.txt"
    # Two paragraphs that together exceed 3000 chars → must produce exactly 2 chunks
    long_text = "Para1\n\n" + ("x" * 3100)
    src.write_text(long_text, encoding="utf-8")

    chunks, name = read_source_by_pages(str(src))
    assert len(chunks) == 2
    assert "Para1" in chunks[0]
    assert "x" * 3100 in chunks[1]
    assert name == "test.txt"

def test_load_index_update_cycle(temp_vault):
    new_index = "# Updated Index\n\n- [[New Page]]"
    update_index(temp_vault, new_index)
    assert load_index(temp_vault) == new_index

def test_append_log(temp_vault):
    append_log(temp_vault, "## [2026-04-17] ingest | Test")
    log = (temp_vault / "log.md").read_text(encoding="utf-8")
    assert "ingest | Test" in log

def test_lint_wiki_empty_vault(temp_vault):
    report = lint_wiki(temp_vault)
    assert isinstance(report, dict)
    assert "broken_wikilinks" in report
    assert len(report["orphan_pages"]) == 0  # index.md is ignored

def test_lint_wiki_detects_orphan_and_broken_link(temp_vault):
    # Create an orphan page
    orphan = temp_vault / "wiki" / "Orphan_Concept.md"
    orphan.write_text("---\ntitle: Orphan Concept\n---\nNo links here.", encoding="utf-8")
    
    # Create a page with broken wikilink
    page = temp_vault / "wiki" / "Main_Page.md"
    page.write_text("---\ntitle: Main Page\n---\nSee [[NonExistent]].", encoding="utf-8")
    
    report = lint_wiki(temp_vault)
    assert "Orphan_Concept.md" in report["orphan_pages"]
    assert any("NonExistent" in broken for broken in report["broken_wikilinks"])