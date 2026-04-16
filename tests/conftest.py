import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import patch, MagicMock

@pytest.fixture
def temp_vault(tmp_path):
    """Create a clean temporary vault for each test."""
    vault = tmp_path / "test-vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki").mkdir(parents=True)
    (vault / "config").mkdir(parents=True)
    (vault / "index.md").write_text("# Wiki Index\n\n", encoding="utf-8")
    (vault / "log.md").write_text("# Activity Log\n\n", encoding="utf-8")
    return vault

@pytest.fixture
def mock_pdf():
    """Correct mock for both read_source() and read_source_by_pages()."""
    with patch("pypdf.PdfReader") as mock_reader:
        # Create two realistic mock pages
        page1 = MagicMock()
        page1.extract_text.return_value = "This is page 1 text."
        page2 = MagicMock()
        page2.extract_text.return_value = "This is page 2 text."
        mock_reader.return_value.pages = [page1, page2]
        yield mock_reader