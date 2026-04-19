import json
import re
import ollama
from rich.console import Console
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

console = Console()

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    undefined=StrictUndefined,   # raises if a variable is missing — catches bugs early
    keep_trailing_newline=True,
)

def _load_prompt(name: str, **kwargs) -> str:
    """Load and render a Jinja prompt template."""
    template = _jinja_env.get_template(f"{name}.jinja")
    return template.render(**kwargs)

def _parse_ingest_response(raw: str, filename: str, date: str) -> dict:
    """
    Parse the plain-text ingest response into the same dict structure
    the rest of the code expects.
    """
    raw = raw.strip()

    if raw == "NOTHING" or raw.startswith("NOTHING"):
        return {"pages": [], "index_update": None, "log_entry": None, "contradictions": []}

    pages = []
    # Extract each PAGE_START...PAGE_END block
    blocks = re.findall(r'PAGE_START\s*(.*?)\s*PAGE_END', raw, re.DOTALL)

    for block in blocks:
        lines = block.strip().splitlines()
        meta = {}
        body_lines = []
        in_body = False

        for line in lines:
            if in_body:
                body_lines.append(line)
            elif line.startswith("filename:"):
                meta["filename"] = line.split(":", 1)[1].strip()
            elif line.startswith("action:"):
                meta["action"] = line.split(":", 1)[1].strip()
            elif line.startswith("title:"):
                meta["title"] = line.split(":", 1)[1].strip()
            elif line.startswith("tags:"):
                meta["tags"] = [t.strip() for t in line.split(":", 1)[1].split(",")]
            elif line.startswith("related:"):
                meta["related"] = [r.strip() for r in line.split(":", 1)[1].split(",")]
            elif line == "":
                # First blank line = end of headers, start of body
                in_body = True

        if "filename" not in meta:
            continue  # skip malformed blocks

        pages.append({
            "filename": meta.get("filename", "Concepts/Untitled.md"),
            "action": meta.get("action", "create"),
            "frontmatter": {
                "title": meta.get("title", "Untitled"),
                "tags": meta.get("tags", []),
                "created": date,
                "updated": date,
                "sources": [f"raw/{filename}"],
                "related": meta.get("related", []),
            },
            "content": "\n".join(body_lines).strip(),
        })

    # Extract summary for log entry
    summary_match = re.search(r'SUMMARY:\s*(.+)', raw)
    summary = summary_match.group(1).strip() if summary_match else "Processed chunk."

    return {
        "pages": pages,
        "index_update": None,   # handled separately — see note below
        "log_entry": summary,
        "contradictions": [],
    }

def _parse_query_response(raw: str) -> dict:
    answer_match = re.search(r'ANSWER\s*(.*?)\s*END_ANSWER', raw, re.DOTALL)
    sources_match = re.search(r'SOURCES\s*(.*?)\s*END_SOURCES', raw, re.DOTALL)
    save_as_match = re.search(r'SAVE_AS\s*(.*?)\s*END_SAVE_AS', raw, re.DOTALL)

    answer = answer_match.group(1).strip() if answer_match else raw.strip()
    sources = [s.strip() for s in sources_match.group(1).strip().splitlines() if s.strip()] if sources_match else []
    save_as = save_as_match.group(1).strip() if save_as_match else "Queries/Answer.md"

    return {"answer": answer, "sources": sources, "save_as": save_as}


class LLM:
    def __init__(self, model: str = "qwen2.5:7b"):
        self.model = model

    def ingest(self, source_text: str, filename: str, index: str, date: str,
           chunk_num: int = 1, total_chunks: int = 1) -> dict:
        """Send one chunk to the LLM and get back structured wiki updates."""
        max_chars = 3000
        if len(source_text) > max_chars:
            source_text = source_text[:max_chars] + "\n\n[...truncated...]"

        prompt = _load_prompt("ingest",
            index=index,
            source_text=source_text,
            filename=filename,
            chunk_num=chunk_num,
            total_chunks=total_chunks,
        )

        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 3000, "think": False},
        )

        raw = response["message"]["content"]
        return _parse_ingest_response(raw, filename, date)

    def find_relevant_pages(self, index: str, question: str) -> list[str]:
        """Ask the LLM which pages in the index are relevant to the question."""
        prompt = _load_prompt("relevance",index=index, question=question)
        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 500, "think": False},
        )
        raw = response["message"]["content"]
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end]).get("pages", [])
        except json.JSONDecodeError:
            console.print("[yellow]Could not parse relevance response, falling back to index scan.[/yellow]")
            filenames = re.findall(r'\(([^)]+\.md)\)', index)
            return filenames[:5]

    def query(self, question: str, pages_content: str) -> dict:
        """Answer a question using the provided wiki page content."""
        prompt = _load_prompt("query",
            question=question,
            pages_content=pages_content,
        )
        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 2000, "think": False},
        )
        return _parse_query_response(response["message"]["content"])

    def lint_suggestions(self, report_text: str, index: str) -> str:
            """Get LLM suggestions based on lint report."""
            prompt = _load_prompt("lint",
                report_text=report_text,
                index=index,
            )
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0, "num_predict": 1500, "think": False},
            )
            return response["message"]["content"].strip()
    
    def create_missing_page(self, page_title: str, referencing_pages: list[str],
                        referencing_content: str, index: str, date: str) -> dict:
        """Create a new wiki page for a broken wikilink target."""
        safe_title = page_title.replace(" ", "_").replace("/", "_")
        prompt = _load_prompt("create_page",
            page_title=page_title,
            safe_title=safe_title,
            referencing_pages=", ".join(referencing_pages),
            referencing_content=referencing_content[:4000],
            index=index,
            date=date,
        )
        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 2500, "think": False},
        )
        raw = response["message"]["content"]

        filename_match = re.search(r'FILENAME\s*(.*?)\s*END_FILENAME', raw, re.DOTALL)
        tags_match = re.search(r'TAGS\s*(.*?)\s*END_TAGS', raw, re.DOTALL)
        related_match = re.search(r'RELATED\s*(.*?)\s*END_RELATED', raw, re.DOTALL)
        content_match = re.search(r'CONTENT\s*(.*?)\s*END_CONTENT', raw, re.DOTALL)

        return {
            "filename": filename_match.group(1).strip() if filename_match else f"Concepts/{safe_title}.md",
            "frontmatter": {
                "title": page_title,
                "tags": [t.strip() for t in tags_match.group(1).split(",")] if tags_match else ["concept"],
                "created": date,
                "updated": date,
                "sources": [],
                "related": [r.strip() for r in related_match.group(1).split(",")] if related_match else [],
            },
            "content": content_match.group(1).strip() if content_match else f"# {page_title}\n",
        }

    def fix_orphan_page(self, orphan_title: str, orphan_content: str,
                    related_content: str, index: str) -> list[dict]:
        """Suggest updates to other pages to link to this orphan."""
        prompt = _load_prompt("fix_orphan",
            orphan_title=orphan_title,
            orphan_content=orphan_content[:2500],
            related_content=related_content[:5000],
            index=index,
        )
        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0, "num_predict": 3000, "think": False},
        )
        raw = response["message"]["content"].strip()

        if raw.startswith("NOTHING"):
            return []

        results = []
        blocks = re.findall(r'PAGE_START\s*(.*?)\s*PAGE_END', raw, re.DOTALL)
        for block in blocks:
            lines = block.strip().splitlines()
            filename = None
            body_lines = []
            in_body = False
            for line in lines:
                if in_body:
                    body_lines.append(line)
                elif line.startswith("filename:"):
                    filename = line.split(":", 1)[1].strip()
                elif line == "":
                    in_body = True
            if filename:
                results.append({"filename": filename, "content": "\n".join(body_lines).strip()})
        return results