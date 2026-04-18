# 🦉 lokiwiki

**A fully local, Obsidian-native implementation of [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).**

Instead of re-deriving answers from raw documents on every query (like RAG), lokiwiki builds a **persistent, compounding knowledge base** — a living wiki of interlinked Markdown pages that grows richer every time you ingest a new source. No cloud. No API keys. Runs entirely on your laptop via [Ollama](https://ollama.com).

> "The LLM is the programmer. The wiki is the codebase. Obsidian is the IDE."
> — Andrej Karpathy

---

## ✨ Features

- **Page-by-page ingestion** — processes PDFs and text files one page at a time, so the LLM builds deep, rich wiki pages rather than shallow summaries
- **Obsidian-native output** — every wiki page has YAML frontmatter, `[[Wikilinks]]`, and tags; open the vault folder directly in Obsidian and get graph view, Dataview queries, and backlinks for free
- **Persistent & compounding** — knowledge accumulates across sessions; new sources update existing pages rather than duplicating them
- **Query your wiki** — ask natural language questions and get answers synthesized from your wiki pages with citations; math and LaTeX rendered correctly in terminal
- **Web article clipping** — save articles via Obsidian Web Clipper to `toBeProcessed/` and batch-ingest them with `process-queue`
- **Lint & autofix** — health-check the wiki for broken wikilinks, orphan pages, missing index entries, and frontmatter issues; auto-fix with `--autofix`
- **Wiki stats dashboard** — instant summary of pages, sources, top tags, most-linked pages, and more — no LLM needed
- **Default vault** — set once with `lokiwiki init`, never type the path again
- **Fully local** — runs on Ollama with quantized models; no data leaves your machine
- **Git versioning** — automatic repo init, backups, and rollback built into the vault

---

## 🏗️ Architecture

```
my-wiki/
├── raw/              ← immutable source documents (PDFs, txt, md)
├── wiki/             ← LLM-generated knowledge base (open this in Obsidian)
│   ├── Concepts/
│   ├── Entities/
│   ├── Sources/
│   ├── Comparisons/
│   └── Queries/
├── toBeProcessed/    ← drop clipped articles here; processed by process-queue
├── config/
│   └── agents.md     ← schema and instructions for the LLM
├── index.md          ← catalog of all wiki pages (LLM reads this on every query)
└── log.md            ← append-only record of all operations
```

Three layers, as described in Karpathy's gist:

| Layer | Description |
|---|---|
| **Raw sources** | Your documents. Immutable. The LLM reads but never modifies these. |
| **Wiki** | LLM-owned Markdown files. Created, updated, and cross-referenced automatically. |
| **Schema** | `config/agents.md` — tells the LLM how to maintain the wiki. |

---

## 🚀 Quickstart

### 1. Install Ollama and pull a model

```bash
# Install Ollama: https://ollama.com
ollama pull qwen2.5:7b   # recommended for 16GB RAM
```

### 2. Install lokiwiki

```bash
git clone https://github.com/ArijitMishra/lokiwiki.git
cd lokiwiki
pip install -e .
```

### 3. Create a vault

```bash
lokiwiki init my-wiki
```

This creates an Obsidian-ready vault and saves it as your default — no need to pass `--vault` on every command.

### 4. Ingest a document

```bash
lokiwiki ingest path/to/paper.pdf
```

lokiwiki processes the document page by page. Each page is sent to the LLM, which creates or updates wiki pages with proper YAML frontmatter and `[[Wikilinks]]`.

### 4b. Clip web articles (optional)

Use [Obsidian Web Clipper](https://obsidian.md/clipper) to save articles directly to `toBeProcessed/`. Configure the clipper with:

- **Save location:** `toBeProcessed/`
- **Filename template:** `{{date}}_{{title}}`
- **Content:** Reader view (strips ads automatically)
- **Images:** Disabled
- **Links:** Strip

Then run:

```bash
lokiwiki process-queue
```

Files are moved to `raw/` automatically on success. Files that fail are left in `toBeProcessed/` for retry.

### 5. Open in Obsidian

Open the `my-wiki/` folder as a vault in Obsidian. Hit `Ctrl+G` for the graph view.

### 6. Query your wiki

```bash
lokiwiki query "What is the main contribution of this paper?"
```

Answers are synthesized from your wiki pages with citations. Math and LaTeX expressions are rendered in the terminal automatically. If the answer contains complex equations, it opens in your browser with full MathJax rendering.

### 7. Check wiki health

```bash
lokiwiki lint              # report only
lokiwiki lint --suggest    # report + LLM suggestions
lokiwiki lint --autofix    # report + LLM fixes broken links and orphans
```

### 8. View wiki stats

```bash
lokiwiki stats
```

---

## 📖 Commands

```
lokiwiki init [VAULT_NAME]    Create an Obsidian-ready vault and set it as default
lokiwiki ingest FILE          Ingest a document page by page into the wiki
lokiwiki process-queue        Ingest all files in toBeProcessed/ and move them to raw/
lokiwiki query "QUESTION"     Ask a question answered from wiki pages
lokiwiki stats                Show a dashboard of wiki statistics (no LLM needed)
lokiwiki lint                 Health-check the wiki for issues
lokiwiki config               View or update lokiwiki settings
lokiwiki init-git             Initialize Git repository in the vault
lokiwiki backup               Create a Git commit of the current vault state
lokiwiki rollback             Rollback to a previous Git commit
```

### Key options

```
lokiwiki ingest FILE --model qwen2.5:7b    Use a specific Ollama model
lokiwiki ingest FILE --start 5             Resume ingestion from page 5
lokiwiki query "..." --save                Save the answer as a new wiki page
lokiwiki lint --autofix                    Automatically fix broken links and orphans
lokiwiki config --set-vault PATH           Change default vault
lokiwiki rollback --list                   List recent Git history
```

---

## ⚙️ Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally
- 8–16 GB RAM (use `qwen2.5:7b` or `llama3.2:3b` for 16 GB machines)

### Python dependencies

```bash
pip install pypdf trafilatura pylatexenc markdown jinja2
```

### Recommended models

| RAM | Model | Notes |
|---|---|---|
| 8 GB | `llama3.2:3b` | Fast, lightweight |
| 16 GB | `qwen2.5:7b` | Best quality/speed tradeoff |
| 32 GB+ | `qwen2.5:14b` | Higher quality output |

---

## 🔧 How it works

### Ingest

```
PDF → split by page → for each page:
    load current index.md
    send page + index to LLM
    LLM returns plain text (PAGE_START...PAGE_END blocks)
    parse response — no JSON, safe for math/LaTeX content
    write wiki pages with frontmatter + wikilinks
    update index.md and log.md
```

The LLM sees the current index on every page, so it knows which pages already exist and updates them rather than creating duplicates. A 30-page paper runs in ~30 LLM calls and produces a rich, interlinked wiki.

If ingestion is interrupted, resume from where you left off:

```bash
lokiwiki ingest paper.pdf --start 15
```

### Query

```
question → LLM reads index.md → identifies relevant pages (up to 5)
         → loads those pages → LLM synthesizes answer with citations
         → math rendered in terminal or browser
         → optionally saves answer as a new wiki page
```

### Lint

Pure Python checks — no LLM needed for the report:

- Broken `[[wikilinks]]` — referenced pages that don't exist
- Orphan pages — pages with no inbound links
- Missing index entries — pages on disk not listed in `index.md`
- Frontmatter issues — missing required fields

With `--autofix`, the LLM creates missing pages and adds links to orphans.

---

## 🗂️ Obsidian Tips

- **Graph view** (`Ctrl+G`) — visualise how concepts connect
- **Dataview plugin** — query your wiki like a database using frontmatter:
  ```
  TABLE tags, updated FROM "wiki" SORT updated DESC
  ```
- **Recommended plugins**: Dataview, Advanced URI
- **Web Clipper**: configure save location to `toBeProcessed/` and run `lokiwiki process-queue` to batch-ingest clipped articles
- **Windows users**: open the vault folder directly in Obsidian on Windows; if running lokiwiki from WSL, point your vault to the Windows filesystem (`/mnt/c/Users/...`)

---

## 🙏 Acknowledgements

Inspired by [Andrej Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (April 2026). lokiwiki is a fully local, Ollama-first implementation of that pattern with native Obsidian compatibility.

---

## 📄 License

MIT