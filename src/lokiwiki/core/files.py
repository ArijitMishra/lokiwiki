from pathlib import Path
import shutil
import re


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

def get_all_wiki_pages(vault_path: Path) -> list[Path]:
    """Return all .md files under wiki/"""
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.exists():
        return []
    return list(wiki_dir.rglob("*.md"))


def lint_wiki(vault_path: Path) -> dict:
    """
    Check the wiki for common issues.
    Returns a report dict with lists of problems found.
    """
    wiki_dir = vault_path / "wiki"
    all_pages = get_all_wiki_pages(vault_path)

    # Build a set of all existing filenames (relative to wiki/)
    existing = {p.relative_to(wiki_dir).as_posix() for p in all_pages}
    existing_stems = {p.stem.lower() for p in all_pages}

    report = {
        "broken_wikilinks": [],   # (source_file, broken_link)
        "orphan_pages": [],       # pages with no inbound links
        "missing_from_index": [], # on disk but not in index.md
        "stale_index_entries": [], # in index.md but not on disk
        "frontmatter_issues": [], # missing required fields
    }

    # --- Check index.md ---
    index_file = vault_path / "index.md"
    index_entries = set()
    if index_file.exists():
        index_text = index_file.read_text(encoding="utf-8")
        index_entries = set(re.findall(r'\(([^)]+\.md)\)', index_text))

    for entry in index_entries:
        if entry not in existing:
            report["stale_index_entries"].append(entry)

    for page_rel in existing:
        if page_rel not in index_entries:
            report["missing_from_index"].append(page_rel)

    # --- Check each page ---
    inbound_links = {rel: 0 for rel in existing}  # count inbound links per page

    for page_path in all_pages:
        content = page_path.read_text(encoding="utf-8", errors="ignore")
        rel = page_path.relative_to(wiki_dir).as_posix()

        # Check frontmatter
        if not content.startswith("---"):
            report["frontmatter_issues"].append(
                f"{rel}: missing YAML frontmatter"
            )
        else:
            for field in ["title", "tags", "sources"]:
                if f"{field}:" not in content[:500]:
                    report["frontmatter_issues"].append(
                        f"{rel}: missing field '{field}'"
                    )

        # Check wikilinks [[Link Name]]
        wikilinks = re.findall(r'\[\[([^\]]+)\]\]', content)
        for link in wikilinks:
            # Strip display text if [[Title|Display]]
            link_target = link.split("|")[0].strip()
            link_slug = link_target.lower().replace(" ", "_")

            # Check if any existing page matches
            matched = any(
                stem == link_slug or stem == link_target.lower()
                for stem in existing_stems
            )
            if not matched:
                report["broken_wikilinks"].append((rel, link_target))
            else:
                # Count inbound link for the target
                for existing_rel in existing:
                    if Path(existing_rel).stem.lower() in (link_slug, link_target.lower()):
                        inbound_links[existing_rel] = inbound_links.get(existing_rel, 0) + 1

    # --- Orphan pages (no inbound links) ---
    for rel, count in inbound_links.items():
        if count == 0:
            report["orphan_pages"].append(rel)

    return report

def read_source_by_pages(source_path: str) -> tuple[list[str], str]:
    """
    Read a source file and return (list_of_page_texts, filename).
    For PDFs: one entry per page.
    For TXT/MD: split by double newline into ~page-sized chunks.
    """
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ImportError("pypdf is required. Run: pip install pypdf")
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            text = text.strip()
            if text:  # skip blank pages
                pages.append(text)
        return pages, path.name

    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Split on double newlines, group into ~3000 char chunks
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) > 3000:
                if current:
                    chunks.append(current)
                current = para
            else:
                current += "\n\n" + para
        if current:
            chunks.append(current)
        return chunks, path.name

    else:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: .txt, .md, .pdf")