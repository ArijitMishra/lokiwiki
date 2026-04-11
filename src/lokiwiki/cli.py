import typer
from pathlib import Path
from datetime import date
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
import json

console = Console()

# Config file lives at ~/.lokiwiki/config.json
CONFIG_DIR = Path.home() / ".lokiwiki"
CONFIG_FILE = CONFIG_DIR / "config.json"


def save_config(vault_path: str):
    CONFIG_DIR.mkdir(exist_ok=True)
    config = {"default_vault": str(vault_path)}
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def get_vault(vault_override: str | None) -> Path:
    if vault_override:
        return Path(vault_override).resolve()
    config = load_config()
    if "default_vault" in config:
        return Path(config["default_vault"])
    console.print("[red]No vault specified.[/red]")
    console.print("Run [bold]lokiwiki init <vault-path>[/bold] first.")
    raise typer.Exit(1)

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
        console.print(f"[yellow]⚠️  Vault already exists:[/yellow] {vault_path}")
        save_config(str(vault_path))
        console.print(f"[green]✅ Set as default vault.[/green]")
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

    save_config(str(vault_path))
    console.print(f"[green]✅ Vault created:[/green] {vault_path}")
    console.print("→ Open this folder in Obsidian")
    console.print("→ Then run: lokiwiki ingest <path-to-file>")

@app.command()
def ingest(
    source_path: str = typer.Argument(..., help="Path to the file to ingest (PDF, TXT, MD)"),
    vault:       str = typer.Option(None, "--vault", "-v", help="Path to your vault folder"),
    model:       str = typer.Option("qwen2.5:7b", "--model", "-m", help="Ollama model to use"),
):
    """Ingest a document into the wiki. The LLM reads it and updates wiki pages."""
    from lokiwiki.core.files import (
        read_source, copy_to_raw, load_index,
        write_wiki_page, update_index, append_log
    )
    from lokiwiki.core.llm import LLM

    vault_path = get_vault(vault)
    if not vault_path.exists():
        console.print(f"[red]Vault not found:[/red] {vault_path}")
        console.print("Run `lokiwiki init` first.")
        raise typer.Exit(1)

    # Step 1: Read the source file
    console.print(f"[blue]📄 Reading source:[/blue] {source_path}")
    try:
        source_text, filename = read_source(source_path)
    except (FileNotFoundError, ValueError, ImportError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Step 2: Copy into raw/
    copy_to_raw(source_path, vault_path)
    console.print(f"[dim]→ Copied to raw/{filename}[/dim]")

    # Step 3: Load current wiki state
    index = load_index(vault_path)
    today = date.today().isoformat()

    # Step 4: Call the LLM
    llm = LLM(model=model)
    console.print(f"[blue]🤖 Sending to LLM ({model})...[/blue]")
    console.print("[dim]   This may take 30–90 seconds on a laptop.[/dim]")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("LLM is reading and synthesizing...", total=None)
        try:
            result = llm.ingest(source_text, filename, index, today)
        except Exception as e:
            console.print(f"[red]LLM error:[/red] {e}")
            console.print("[dim]Is Ollama running? Try: ollama serve[/dim]")
            raise typer.Exit(1)

    # Step 5: Write wiki pages
    pages = result.get("pages", [])
    console.print(f"[green]✅ LLM returned {len(pages)} page(s) to write.[/green]")

    for page in pages:
        filename_out = page.get("filename", "untitled.md")
        fm = page.get("frontmatter", {})
        body = page.get("content", "")

        # Build YAML frontmatter manually (keeps it readable)
        tags_str = "[" + ", ".join(fm.get("tags", [])) + "]"
        related_str = "[" + ", ".join(f'"{r}"' for r in fm.get("related", [])) + "]"
        sources_str = "[" + ", ".join(f'"{s}"' for s in fm.get("sources", [])) + "]"

        full_content = f"""---
title: "{fm.get('title', filename_out)}"
tags: {tags_str}
created: "{fm.get('created', today)}"
updated: "{fm.get('updated', today)}"
sources: {sources_str}
related: {related_str}
---

{body}
"""
        write_wiki_page(vault_path, filename_out, full_content)
        console.print(f"   [dim]Wrote:[/dim] wiki/{filename_out}")

    # Step 6: Update index and log
    if result.get("index_update"):
        update_index(vault_path, result["index_update"])
        console.print("[dim]→ index.md updated[/dim]")

    if result.get("log_entry"):
        append_log(vault_path, result["log_entry"])
        console.print("[dim]→ log.md updated[/dim]")

    # Report any contradictions the LLM flagged
    contradictions = result.get("contradictions", [])
    if contradictions:
        console.print("\n[yellow]⚠️  Contradictions flagged by LLM:[/yellow]")
        for c in contradictions:
            console.print(f"   • {c}")

    console.print(f"\n[green]✅ Ingest complete.[/green] Open your vault in Obsidian to explore.")

@app.command()
def config(
    set_vault: str = typer.Option(None, "--set-vault", help="Set a new default vault path"),
):
    """View or update lokiwiki configuration."""
    if set_vault:
        save_config(set_vault)
        console.print(f"[green]✅ Default vault set to:[/green] {set_vault}")
        return
    cfg = load_config()
    if cfg:
        console.print(f"Default vault: [bold]{cfg.get('default_vault', 'not set')}[/bold]")
    else:
        console.print("[yellow]No config found. Run `lokiwiki init <path>` to set a default vault.[/yellow]")

@app.command()
def query(
    question: str = typer.Argument(..., help="Question to ask your wiki"),
    vault:    str = typer.Option(None, "--vault", "-v", help="Vault path (uses default if not set)"),
    model:    str = typer.Option("qwen2.5:7b", "--model", "-m", help="Ollama model to use"),
    save:     bool = typer.Option(False, "--save", "-s", help="Save the answer as a new wiki page"),
):
    """Ask a question and get an answer synthesized from your wiki."""
    from lokiwiki.core.files import load_index, load_wiki_pages, write_wiki_page, append_log
    from lokiwiki.core.llm import LLM

    vault_path = get_vault(vault)
    index = load_index(vault_path)
    llm = LLM(model=model)

    # Step 1: Find relevant pages
    console.print(f"[blue]🔍 Finding relevant pages...[/blue]")
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("Searching index...", total=None)
        relevant = llm.find_relevant_pages(index, question)

    if not relevant:
        console.print("[yellow]No relevant pages found in the wiki. Try ingesting more documents first.[/yellow]")
        raise typer.Exit()

    console.print(f"[dim]Relevant pages: {', '.join(relevant)}[/dim]")

    # Step 2: Load those pages
    pages_content = load_wiki_pages(vault_path, relevant)
    if not pages_content:
        console.print("[yellow]Could not load page content.[/yellow]")
        raise typer.Exit()

    # Step 3: Get the answer
    console.print(f"[blue]🤖 Synthesizing answer...[/blue]")
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("LLM is thinking...", total=None)
        try:
            result = llm.query(question, pages_content)
        except Exception as e:
            console.print(f"[red]LLM error:[/red] {e}")
            raise typer.Exit(1)

    # Step 4: Print the answer
    console.print("\n" + "─" * 60)
    console.print(f"[bold]Q: {question}[/bold]\n")
    console.print(result.get("answer", "No answer returned."))
    console.print("\n[dim]Sources: " + ", ".join(result.get("sources", [])) + "[/dim]")
    console.print("─" * 60)

    # Step 5: Optionally save as wiki page
    if save or typer.confirm("\nSave this answer as a wiki page?", default=False):
        today = date.today().isoformat()
        suggested = result.get("save_as", "Queries/Answer.md")
        filename = f"Queries/{suggested}" if "/" not in suggested else suggested

        content = f"""---
title: "{question}"
tags: [query, answer]
created: "{today}"
updated: "{today}"
sources: {json.dumps(result.get("sources", []))}
related: []
---

**Q: {question}**

{result.get("answer", "")}

## Sources
{chr(10).join(f"- [[{s}]]" for s in result.get("sources", []))}
"""
        write_wiki_page(vault_path, filename, content)
        append_log(vault_path, f"## [{today}] query | {question}\n\nSaved as {filename}.")
        console.print(f"[green]✅ Saved to wiki/{filename}[/green]")        

if __name__ == "__main__":
    app()