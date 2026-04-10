import typer
from pathlib import Path
from rich.console import Console

console = Console()

app = typer.Typer(
    help="Local LLM Wiki with Obsidian support – inspired by Karpathy's LLM Wiki",
    no_args_is_help=True,
)

@app.command()
def init(
    vault_name: str = typer.Argument("my-wiki", help="Name of the vault folder to create")
):
    """Initialize a new Obsidian-ready LLM Wiki vault."""
    vault_path = Path(vault_name).resolve()

    if vault_path.exists():
        console.print(f"[yellow]⚠️ Vault '{vault_name}' already exists.[/yellow]")
        return

    (vault_path / "raw").mkdir(parents=True, exist_ok=True)
    (vault_path / "wiki").mkdir(parents=True, exist_ok=True)
    (vault_path / "config").mkdir(parents=True, exist_ok=True)

    (vault_path / "index.md").write_text("# My LLM Wiki Index\n\n", encoding="utf-8")
    (vault_path / "log.md").write_text("# Ingestion Log\n\n", encoding="utf-8")

    agents_content = """# LLM Wiki — Agent Schema (Obsidian Edition)

This file is the schema and operating instructions for the LLM that maintains this wiki.
It defines conventions, workflows, and rules the LLM must follow across all sessions.

---

## Architecture

Three layers:

- **raw/**    → Immutable source documents. The LLM reads but never modifies these.
               Drop PDFs, articles, notes, transcripts here before ingesting.
- **wiki/**   → LLM-owned knowledge base. The LLM creates and updates all files here.
               Open this entire vault folder in Obsidian.
- **config/** → This schema file and any other configuration.

Two special files at the vault root:
- **index.md** → Content-oriented catalog. Lists every wiki page with a one-line summary,
                 organized by category (Concepts, Entities, Sources, Comparisons, etc.).
                 The LLM reads this first on every query to find relevant pages.
                 Updated on every ingest.
- **log.md**   → Append-only chronological record of all operations (ingests, queries,
                 lint passes). Each entry starts with `## [YYYY-MM-DD] operation | title`
                 so entries are grep-parseable.

---

## Obsidian Conventions (MANDATORY)

Every page in wiki/ MUST have YAML frontmatter:

```yaml
---
title: "Exact Page Title"
tags: [concept, ai, transformers]
created: "2026-04-11"
updated: "2026-04-11"
sources: ["raw/paper.pdf"]
related: ["[[Self-Attention]]", "[[Positional Encoding]]"]
---
```

- Use [[Wikilinks]] for ALL internal references — never plain text references to other pages.
- Filenames must match the title (spaces → underscores). E.g. `Self_Attention.md`.
- Every page should have a short summary paragraph immediately after frontmatter.
- Place a `## Sources` section at the bottom listing the raw files that informed this page.
- Organize wiki/ into subdirectories: Concepts/, Entities/, Sources/, Comparisons/.

---

## Operations

### Ingest
Triggered when the user drops a file into raw/ and asks the LLM to process it.

Workflow:
1. Read the source document fully.
2. Discuss key takeaways with the user (optional but preferred for one-at-a-time ingestion).
3. Write a summary page in wiki/Sources/ for the source itself.
4. Create or update concept/entity pages in wiki/Concepts/ and wiki/Entities/.
   A single source can touch 10-15 pages — this is expected and desirable.
5. Note any contradictions with existing wiki content explicitly, in both pages involved.
6. Update index.md — add new pages, update summaries of changed pages.
7. Append an entry to log.md: `## [date] ingest | Source Title`

### Query
Triggered when the user asks a question.

Workflow:
1. Read index.md to identify relevant pages.
2. Read the relevant pages in full.
3. Synthesize an answer with citations linking to wiki pages.
4. If the answer is non-trivial, offer to save it as a new wiki page — good answers
   compound the knowledge base just like sources do.

### Lint
Triggered when the user asks for a health check.

Check for:
- Contradictions between pages
- Stale claims superseded by newer sources
- Orphan pages (no inbound [[wikilinks]])
- Important concepts mentioned but lacking their own page
- Missing cross-references between obviously related pages
- Frontmatter inconsistencies (missing fields, malformed tags)
- Suggest new questions to investigate or sources to look for

---

## Key Principles

- The wiki is a **persistent, compounding artifact**. Every session should leave it
  richer than before.
- The LLM does all the bookkeeping (cross-references, updates, consistency).
  The human curates sources and asks questions.
- Knowledge is **compiled once and kept current** — not re-derived from raw sources
  on every query.
- Prefer updating existing pages over creating new ones for incremental information.
  Create new pages when a concept deserves its own entry.
- When in doubt about categorization, put it in Concepts/ and link liberally.
"""
    (vault_path / "config" / "agents.md").write_text(agents_content, encoding="utf-8")

    console.print(f"[green]✅ Vault created:[/green] {vault_path}")

@app.command()
def ingest(
    source_path: str = typer.Argument(..., help="Path to file or folder to ingest (PDF, TXT, MD, etc.)")
):
    """Ingest a document into the wiki using the LLM (Obsidian compatible)."""
    console.print(f"[blue]🚀 Ingesting:[/blue] {source_path}")
    # TODO: Implement full logic in next step
    console.print("[yellow]Ingest command skeleton ready. Full implementation coming next.[/yellow]")

if __name__ == "__main__":
    app()