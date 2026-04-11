from pathlib import Path
import shutil


def read_source(source_path: str) -> tuple[str, str]:
    """
    Read a source file and return (text_content, filename).
    Supports: .txt, .md, .pdf
    """
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    suffix = path.suffix.lower()

    if suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")

    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ImportError("pypdf is required for PDF ingestion. Run: pip install pypdf")
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages)

    else:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: .txt, .md, .pdf")

    return text, path.name


def copy_to_raw(source_path: str, vault_path: Path) -> Path:
    """Copy the source file into vault/raw/ and return the destination path."""
    raw_dir = vault_path / "raw"
    raw_dir.mkdir(exist_ok=True)
    dest = raw_dir / Path(source_path).name
    if not dest.exists():
        shutil.copy2(source_path, dest)
    return dest


def load_index(vault_path: Path) -> str:
    """Load the current index.md content, or return empty string."""
    index_file = vault_path / "index.md"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return "# Wiki Index\n\n(empty)"


def write_wiki_page(vault_path: Path, filename: str, content: str):
    """Write a page to vault/wiki/, creating subdirs as needed."""
    wiki_dir = vault_path / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    page_path = wiki_dir / filename
    # Create subdirectory if filename includes one (e.g. "Concepts/Attention.md")
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(content, encoding="utf-8")


def update_index(vault_path: Path, new_index: str):
    """Overwrite index.md with the updated content."""
    (vault_path / "index.md").write_text(new_index, encoding="utf-8")


def append_log(vault_path: Path, entry: str):
    """Append an entry to log.md."""
    log_file = vault_path / "log.md"
    existing = log_file.read_text(encoding="utf-8") if log_file.exists() else "# Activity Log\n\n"
    log_file.write_text(existing + entry + "\n\n", encoding="utf-8")

def load_wiki_pages(vault_path: Path, filenames: list[str]) -> str:
    """Load the content of specific wiki pages and return as a combined string."""
    combined = []
    for filename in filenames:
        page_path = vault_path / "wiki" / filename
        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            combined.append(f"### {filename}\n\n{content}")
        else:
            # Try without the subdirectory prefix
            for found in (vault_path / "wiki").rglob(Path(filename).name):
                content = found.read_text(encoding="utf-8")
                combined.append(f"### {filename}\n\n{content}")
                break
    return "\n\n---\n\n".join(combined)