import typer
from pathlib import Path
from datetime import date
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
import json
import subprocess

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

    try:
        git_dir = vault_path / ".git"
        if git_dir.exists():
            console.print("[green]Git repository already exists.[/green]")
        else:
            subprocess.run(["git", "init"], cwd=vault_path, check=True, capture_output=True)
            
            # Create useful .gitignore
            gitignore_path = vault_path / ".gitignore"
            gitignore_path.write_text(
                """# Lokiwiki Gitignore
raw/                  # Raw source files (immutable, usually large)
.obsidian/            # Obsidian workspace settings (optional)
llm_raw_output.txt    # Temporary debug files
*.tmp

# Ignore large binaries if any
*.pdf
*.jpg
*.png
""",
                encoding="utf-8"
            )

            # Stage and make initial commit
            subprocess.run(["git", "add", "."], cwd=vault_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial lokiwiki vault setup"],
                cwd=vault_path,
                check=True,
                capture_output=True
            )
            git_initialized = True
            console.print("[green]✅ Git repository initialized with initial commit.[/green]")

    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Git init failed (git may not be installed): {e.stderr.decode() if e.stderr else e}[/yellow]")
        console.print("[dim]You can run `lokiwiki init-git` manually later.[/dim]")
    except FileNotFoundError:
        console.print("[yellow]Git command not found. Please install Git to enable automatic versioning.[/yellow]")

    save_config(str(vault_path))
    console.print(f"[green]✅ Vault created:[/green] {vault_path}")
    console.print("→ Open this folder in Obsidian")
    console.print("→ Then run: lokiwiki ingest <path-to-file>")

@app.command()
def init_git(
    vault: str = typer.Option(None, "--vault", "-v")
):
    """Initialize Git repository in the vault for versioning."""
    vault_path = get_vault(vault)
    git_dir = vault_path / ".git"
    
    if git_dir.exists():
        console.print("[green]✅ Git repository already initialized.[/green]")
        return
    
    try:
        import subprocess
        subprocess.run(["git", "init"], cwd=vault_path, check=True, capture_output=True)
        
        # Create a sensible .gitignore
        gitignore = vault_path / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("""# Ignore raw sources (immutable)
raw/
# Ignore Obsidian config if you don't want to version it
.obsidian/
# Ignore temporary files
*.tmp
llm_raw_output.txt
""", encoding="utf-8")
        
        # Initial commit
        subprocess.run(["git", "add", "."], cwd=vault_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial lokiwiki vault commit"], 
                      cwd=vault_path, check=True)
        
        console.print(f"[green]✅ Git repository initialized in {vault_path}[/green]")
        console.print("   You can now use `lokiwiki backup` and `lokiwiki rollback`")
        
    except Exception as e:
        console.print(f"[red]Failed to initialize Git: {e}[/red]")

@app.command()
def backup(
    vault: str = typer.Option(None, "--vault", "-v"),
    message: str = typer.Option("lokiwiki autofix / ingest", "--message", "-m")
):
    """Create a new version (Git commit) of the current wiki state."""
    vault_path = get_vault(vault)
    
    if not (vault_path / ".git").exists():
        console.print("[yellow]Git not initialized. Run `lokiwiki init-git` first.[/yellow]")
        return
    
    try:
        import subprocess
        subprocess.run(["git", "add", "wiki/", "index.md", "log.md"], cwd=vault_path, check=True)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=vault_path, capture_output=True, text=True
        )
        
        if result.returncode == 0:
            console.print(f"[green]✅ Backup created: {message}[/green]")
        else:
            if "nothing to commit" in result.stdout.lower():
                console.print("[yellow]No changes to backup.[/yellow]")
            else:
                console.print(f"[red]Commit failed: {result.stderr}[/red]")
    except Exception as e:
        console.print(f"[red]Backup failed: {e}[/red]")


@app.command()
def rollback(
    vault: str = typer.Option(None, "--vault", "-v"),
    steps: int = typer.Option(1, "--steps", "-s", help="How many commits to go back"),
    list_only: bool = typer.Option(False, "--list", "-l", help="Just list history")
):
    """Revert to a previous version of the wiki."""
    vault_path = get_vault(vault)
    git_dir = vault_path / ".git"
    
    if not git_dir.exists():
        console.print("[red]Git not initialized in this vault.[/red]")
        return
    
    try:
        import subprocess
        
        if list_only:
            result = subprocess.run(["git", "log", "--oneline", "-10"], 
                                  cwd=vault_path, capture_output=True, text=True)
            console.print("[bold]Recent versions:[/bold]")
            console.print(result.stdout)
            return
        
        # Show history and let user choose
        result = subprocess.run(["git", "log", "--oneline", "-20"], 
                              cwd=vault_path, capture_output=True, text=True)
        console.print(result.stdout)
        
        commit = typer.prompt("Enter commit hash (or 'HEAD~n') to rollback to")
        
        if typer.confirm(f"⚠️  This will reset wiki/ to {commit}. Continue?", default=False):
            subprocess.run(["git", "reset", "--hard", commit], cwd=vault_path, check=True)
            console.print(f"[green]✅ Rolled back to {commit}[/green]")
            console.print("   Open your vault in Obsidian to see the previous state.")
        
    except Exception as e:
        console.print(f"[red]Rollback failed: {e}[/red]")


@app.command()
def ingest(
    source_path: str = typer.Argument(..., help="Path to file or folder to ingest (PDF, TXT, MD)"),
    vault:  str  = typer.Option(None, "--vault",  "-v", help="Vault path (uses default if not set)"),
    model:  str  = typer.Option("qwen2.5:7b", "--model", "-m", help="Ollama model to use"),
    start_page: int = typer.Option(1, "--start", "-s", help="Start from this page/chunk number (1-indexed)"),
):
    """Ingest a document page-by-page into the wiki."""
    from lokiwiki.core.files import (
        read_source_by_pages, copy_to_raw, load_index,
        write_wiki_page, update_index, append_log
    )
    from lokiwiki.core.llm import LLM
    from pathlib import Path

    vault_path = get_vault(vault)
    if not vault_path.exists():
        console.print(f"[red]Vault not found:[/red] {vault_path}")
        raise typer.Exit(1)

    # Determine files to process (auto-detect directory, non-recursive)
    src = Path(source_path)
    supported_exts = {".pdf", ".txt", ".md"}
    if src.is_dir():
        files_to_process = [p for p in src.iterdir() if p.suffix.lower() in supported_exts]
        if not files_to_process:
            console.print(f"[red]No supported files found in directory:[/red] {src}")
            raise typer.Exit(1)
    else:
        files_to_process = [src]

    llm = LLM(model=model)
    today = date.today().isoformat()

    pages_written = 0
    total_chunks_processed = 0

    # Process each file found
    for file_path in files_to_process:
        console.print(f"[blue]📄 Reading source:[/blue] {file_path}")
        try:
            pages, filename = read_source_by_pages(str(file_path))
        except (FileNotFoundError, ValueError, ImportError) as e:
            console.print(f"[red]Error reading {file_path}:[/red] {e}")
            continue

        total = len(pages)
        console.print(f"[dim]→ Found {total} pages/chunks to process[/dim]")

        # Copy to raw/ for this file
        copy_to_raw(str(file_path), vault_path)
        console.print(f"[dim]→ Copied to raw/{filename}[/dim]")

        start_idx = max(0, start_page - 1)  # convert to 0-indexed; applies per file

        for i, page_text in enumerate(pages[start_idx:], start=start_idx + 1):

            console.print(f"\n[blue]🤖 Processing page {i}/{total}...[/blue]")

            # Always reload index so LLM sees pages created in previous chunks
            index = load_index(vault_path)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True
            ) as progress:
                progress.add_task(f"LLM reading page {i}/{total}...", total=None)
                try:
                    result = llm.ingest(
                        source_text=page_text,
                        filename=filename,
                        index=index,
                        date=today,
                        chunk_num=i,
                        total_chunks=total,
                    )
                except Exception as e:
                    console.print(f"[red]LLM error on page {i} of {filename}:[/red] {e}")
                    console.print("[dim]Skipping this page and continuing...[/dim]")
                    continue

            # Step 4: Write pages
            pages_result = result.get("pages", [])
            for page in pages_result:
                filename_out = page.get("filename", "untitled.md")
                fm = page.get("frontmatter", {})
                body = page.get("content", "")
                action = page.get("action", "create")

                tags_str    = "[" + ", ".join(fm.get("tags", [])) + "]"
                related_str = "[" + ", ".join(f'"{r}"' for r in fm.get("related", [])) + "]"
                sources_str = "[" + ", ".join(f'"{s}"' for s in fm.get("sources", [])) + "]"

                full_content = f"""---
title: "{fm.get('title', filename_out)}"
tags: {tags_str}
created: "{fm.get('created', today)}"
updated: "{today}"
sources: {sources_str}
related: {related_str}
---

{body}
"""
                write_wiki_page(vault_path, filename_out, full_content)
                pages_written += 1
                console.print(f"   [dim][{action}][/dim] wiki/{filename_out}")

            # Step 5: Update index and log after each chunk
                pages_result = result.get("pages", [])
                if pages_result:
                    index_file = vault_path / "index.md"
                    current_index = index_file.read_text(encoding="utf-8")
                    new_entries = []
                    for page in pages_result:
                        fm = page["frontmatter"]
                        title = fm.get("title", "Untitled")
                        fname = page.get("filename", "")
                        tags = ", ".join(fm.get("tags", []))
                        entry = f"- [{title}]({fname}) — {tags}"
                        # Only add if not already in index
                        if fname not in current_index:
                            new_entries.append(entry)
                    if new_entries:
                        updated_index = current_index.rstrip() + "\n" + "\n".join(new_entries) + "\n"
                        update_index(vault_path, updated_index)

                if result.get("log_entry"):
                    today = date.today().isoformat()
                    append_log(vault_path, f"## [{today}] ingest chunk {i}/{total} | {filename}\n\n{result['log_entry']}")

            contradictions = result.get("contradictions", [])
            if contradictions:
                console.print(f"   [yellow]⚠️  Contradictions:[/yellow]")
                for c in contradictions:
                    console.print(f"      • {c}")

            total_chunks_processed += 1

    console.print(f"\n[green]✅ Ingest complete.[/green] {pages_written} page(s) written across {total_chunks_processed} chunks.")
    console.print("[dim]Open your vault in Obsidian to explore the updated wiki.[/dim]")


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

@app.command()
def lint(
    vault:    str  = typer.Option(None,  "--vault",   "-v", help="Vault path"),
    model:    str  = typer.Option("qwen2.5:7b", "--model", "-m", help="Ollama model"),
    suggest:  bool = typer.Option(False, "--suggest",  "-s", help="Get LLM suggestions only"),
    autofix:  bool = typer.Option(False, "--autofix",  "-a", help="Let LLM automatically fix broken links and orphans"),
):
    """Health-check the wiki and optionally auto-fix issues with LLM."""
    from lokiwiki.core.files import (
        lint_wiki, 
        load_index, 
        load_page_content, 
        write_wiki_page
    )
    from lokiwiki.core.llm import LLM
    from datetime import date
    from rich.progress import Progress, SpinnerColumn, TextColumn
    import re
    from pathlib import Path

    vault_path = get_vault(vault)
    console.print(f"[blue]🔍 Linting wiki:[/blue] {vault_path}")

    report = lint_wiki(vault_path)

    # ====================== PRINT REPORT ======================
    console.print("\n" + "─" * 70)

    if report.get("broken_wikilinks"):
        console.print(f"\n[red]❌ Broken wikilinks ({len(report['broken_wikilinks'])}):[/red]")
        for source, link in report["broken_wikilinks"]:
            console.print(f"   {source} → [[{link}]]")
    else:
        console.print("\n[green]✅ No broken wikilinks[/green]")

    if report.get("orphan_pages"):
        console.print(f"\n[yellow]⚠️  Orphan pages ({len(report['orphan_pages'])}):[/yellow]")
        for p in report["orphan_pages"]:
            console.print(f"   {p}")
    else:
        console.print("[green]✅ No orphan pages[/green]")

    if report.get("missing_from_index"):
        console.print(f"\n[yellow]⚠️  Missing from index ({len(report['missing_from_index'])}):[/yellow]")
        for p in report["missing_from_index"]:
            console.print(f"   {p}")
    else:
        console.print("[green]✅ Index is complete[/green]")

    if report.get("stale_index_entries"):
        console.print(f"\n[red]❌ Stale index entries ({len(report['stale_index_entries'])}):[/red]")
        for p in report["stale_index_entries"]:
            console.print(f"   {p}")
    else:
        console.print("[green]✅ No stale index entries[/green]")

    if report.get("frontmatter_issues"):
        console.print(f"\n[yellow]⚠️  Frontmatter issues ({len(report['frontmatter_issues'])}):[/yellow]")
        for issue in report["frontmatter_issues"]:
            console.print(f"   {issue}")
    else:
        console.print("[green]✅ All frontmatter looks good[/green]")

    console.print("\n" + "─" * 70)

    # ====================== PURE PYTHON FIXES ======================
    if report.get("missing_from_index"):
        if typer.confirm("\nAuto-fix: Add missing pages to index.md?", default=True):
            index_file = vault_path / "index.md"
            current = index_file.read_text(encoding="utf-8")
            additions = []
            for rel in report["missing_from_index"]:
                title = Path(rel).stem.replace("_", " ")
                additions.append(f"- [{title}]({rel})")
            new_content = current.rstrip() + "\n" + "\n".join(additions) + "\n"
            index_file.write_text(new_content, encoding="utf-8")
            console.print(f"[green]✅ Added {len(additions)} pages to index.md[/green]")

    # ====================== LLM AUTOFIX ======================
    if autofix:
        if typer.confirm("Create a backup before autofix?", default=True):
            backup(vault=vault, message="Pre-autofix backup")
        console.print("\n[blue]🤖 Starting LLM-powered autofix...[/blue]")
        llm = LLM(model=model)
        index = load_index(vault_path)
        today = date.today().isoformat()

        # 1. Fix broken wikilinks by creating missing pages
        if report.get("broken_wikilinks"):
            # Group by target link title
            broken_grouped: dict[str, list[str]] = {}
            for source, link in report["broken_wikilinks"]:
                broken_grouped.setdefault(link, []).append(source)

            console.print(f"\n[blue]Creating {len(broken_grouped)} missing page(s)...[/blue]")

            for link_title, sources in broken_grouped.items():
                console.print(f"   → [[{link_title}]]")
                ref_content = "\n\n---\n\n".join(
                    load_page_content(vault_path, src) for src in sources
                )

                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
                    progress.add_task(f"Creating [[{link_title}]]...", total=None)

                    try:
                        page_data = llm.create_missing_page(
                            link_title, sources, ref_content, index, today
                        )

                        filename = page_data.get("filename", f"Concepts/{link_title.replace(' ', '_')}.md")
                        fm = page_data.get("frontmatter", {})
                        content = page_data.get("content", f"# {link_title}\n\nTODO: Add content from context.")

                        full_content = f"""---
title: "{fm.get('title', link_title)}"
tags: {fm.get('tags', ['concept'])}
created: "{today}"
updated: "{today}"
sources: []
related: {fm.get('related', [])}
---

{content}
"""
                        write_wiki_page(vault_path, filename, full_content)
                        console.print(f"   [green]✅ Created:[/green] wiki/{filename}")
                    except Exception as e:
                        console.print(f"   [red]Failed to create {link_title}:[/red] {e}")

        # 2. Fix orphan pages by adding links from related pages
        if report.get("orphan_pages"):
            console.print(f"\n[blue]Fixing {len(report['orphan_pages'])} orphan page(s)...[/blue]")

            for orphan_rel in report["orphan_pages"]:
                orphan_title = Path(orphan_rel).stem.replace("_", " ")
                console.print(f"   → {orphan_title}")

                orphan_content = load_page_content(vault_path, orphan_rel)

                # Load a small sample of other pages for context (limit to avoid token explosion)
                all_pages = list((vault_path / "wiki").rglob("*.md"))
                sample_pages = [p for p in all_pages 
                               if p.relative_to(vault_path / "wiki").as_posix() != orphan_rel][:5]

                related_content = "\n\n---\n\n".join(
                    p.read_text(encoding="utf-8", errors="ignore") for p in sample_pages
                )

                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
                    progress.add_task(f"Finding links for {orphan_title}...", total=None)

                    try:
                        updates = llm.fix_orphan_page(
                            orphan_title, orphan_content, related_content, index
                        )
                        for update in updates[:3]:  # safety limit
                            filename = update.get("filename")
                            new_content = update.get("content")
                            if filename and new_content:
                                write_wiki_page(vault_path, filename, new_content)
                                console.print(f"   [green]✅ Updated:[/green] wiki/{filename}")
                    except Exception as e:
                        console.print(f"   [red]Failed for {orphan_title}:[/red] {e}")

        console.print(f"\n[green]✅ LLM Autofix completed.[/green]")

    # ====================== LLM SUGGESTIONS (non-destructive) ======================
    elif suggest:
        console.print("\n[blue]🤖 Getting LLM suggestions...[/blue]")
        index = load_index(vault_path)
        llm = LLM(model=model)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
            progress.add_task("LLM is reviewing the wiki...", total=None)
            suggestions = llm.lint_suggestions(str(report), index)
        console.print("\n[bold]LLM Suggestions:[/bold]")
        console.print(suggestions)

if __name__ == "__main__":
    app()