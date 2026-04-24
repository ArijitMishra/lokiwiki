"""
lokiwiki Phase 2 Benchmark Runner
Measures: ingest time, query latency, tokens/sec, citation accuracy, parse failure rate.
No LLM judge required — all metrics are pure Python or derived from Ollama response stats.

Usage:
    python benchmarks/benchmark.py \
        --models "qwen2.5:7b qwen3.5:9b" \
        --vault-base /tmp/lokiwiki-bench \
        --data-dir benchmarks/data \
        --output benchmarks/results \
        --runs 1
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Make sure lokiwiki src is importable when run from repo root ──────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lokiwiki.core.files import (
    read_source_by_pages,
    load_index,
    write_wiki_page,
    update_index,
    append_log,
    get_all_wiki_pages,
)
from lokiwiki.core.llm import LLM, _parse_ingest_response


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IngestMetrics:
    model: str
    source_file: str
    total_chunks: int
    chunks_with_pages: int       # chunks that produced at least one PAGE_START block
    chunks_failed_parse: int     # chunks with no PAGE_START block at all
    pages_written: int
    total_time_sec: float
    time_per_chunk_sec: float
    tokens_in: int
    tokens_out: int
    tokens_per_sec: float        # eval_rate from Ollama if available


@dataclass
class QueryMetrics:
    model: str
    question_id: str
    question: str
    latency_sec: float
    answer_length_chars: int
    sources_cited: int           # number of pages listed in SOURCES block
    citation_accuracy: float     # % of cited pages that actually exist on disk
    answered_or_declined: bool   # True if answer is non-empty or explicit decline
    tokens_in: int
    tokens_out: int
    tokens_per_sec: float


@dataclass
class ModelSummary:
    model: str
    run: int
    # Ingest aggregates
    total_ingest_time_sec: float = 0.0
    avg_ingest_time_per_chunk_sec: float = 0.0
    total_parse_failures: int = 0
    parse_failure_rate: float = 0.0      # failures / total chunks
    total_pages_written: int = 0
    avg_ingest_tokens_per_sec: float = 0.0
    # Query aggregates
    avg_query_latency_sec: float = 0.0
    avg_citation_accuracy: float = 0.0
    queries_answered: int = 0            # non-empty, non-declined responses
    avg_query_tokens_per_sec: float = 0.0

@dataclass
class JudgeCase:
    question_id: str
    question: str
    question_type: str          # factual / synthesis / edge_case
    reference_answer: str | None
    model: str
    answer: str
    sources_cited: list[str]
    wiki_pages_used: str        # actual content of pages the model drew from

# ─────────────────────────────────────────────────────────────────────────────
# Vault setup helpers
# ─────────────────────────────────────────────────────────────────────────────

def create_fresh_vault(base_dir: Path, model: str, run: int) -> Path:
    """Create an isolated throwaway vault for one benchmark run."""
    safe_model = model.replace(":", "_").replace(".", "_")
    vault_path = base_dir / f"bench_{safe_model}_run{run}"
    if vault_path.exists():
        shutil.rmtree(vault_path)
    for subdir in ["raw", "wiki", "config", "toBeProcessed"]:
        (vault_path / subdir).mkdir(parents=True, exist_ok=True)
    (vault_path / "index.md").write_text("# Benchmark Wiki Index\n\n", encoding="utf-8")
    (vault_path / "log.md").write_text("# Benchmark Log\n\n", encoding="utf-8")
    return vault_path


def copy_sources_to_raw(vault_path: Path, sample_dir: Path) -> list[Path]:
    """Copy benchmark sample articles into vault/raw/ and return paths."""
    supported = {".pdf", ".txt", ".md"}
    sources = [f for f in sample_dir.iterdir() if f.suffix.lower() in supported]
    if not sources:
        raise FileNotFoundError(f"No supported files found in {sample_dir}")
    for src in sources:
        dest = vault_path / "raw" / src.name
        shutil.copy2(src, dest)
    return [vault_path / "raw" / s.name for s in sources]


# ─────────────────────────────────────────────────────────────────────────────
# Citation accuracy check
# ─────────────────────────────────────────────────────────────────────────────

def check_citation_accuracy(vault_path: Path, cited_pages: list[str]) -> float:
    """
    Given a list of filenames cited in SOURCES, check what % actually exist
    on disk under vault/wiki/.
    Returns 1.0 if cited_pages is empty (nothing to check).
    """
    if not cited_pages:
        return 1.0
    wiki_dir = vault_path / "wiki"
    existing = {p.relative_to(wiki_dir).as_posix() for p in wiki_dir.rglob("*.md")}
    existing_names = {p.name for p in wiki_dir.rglob("*.md")}
    hits = 0
    for citation in cited_pages:
        citation = citation.strip()
        # Match either full relative path or just filename
        if citation in existing or Path(citation).name in existing_names:
            hits += 1
    return hits / len(cited_pages)


# ─────────────────────────────────────────────────────────────────────────────
# Ingest benchmark
# ─────────────────────────────────────────────────────────────────────────────

def benchmark_ingest(
    model: str,
    vault_path: Path,
    source_files: list[Path],
    today: str,
) -> list[IngestMetrics]:
    """Run ingest on all source files and return per-file metrics."""
    llm = LLM(model=model)
    results = []

    for source_file in source_files:
        print(f"  Ingesting {source_file.name} with {model}...")
        try:
            pages, filename = read_source_by_pages(str(source_file))
        except Exception as e:
            print(f"  ⚠ Could not read {source_file.name}: {e}")
            continue

        total_chunks = len(pages)
        chunks_with_pages = 0
        chunks_failed_parse = 0
        pages_written = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_tokens_per_sec_samples = []
        t_start = time.perf_counter()

        for i, page_text in enumerate(pages, start=1):
            index = load_index(vault_path)
            try:
                # Time the raw ollama call so we can extract token stats
                import ollama as _ollama
                prompt_for_stats = _build_ingest_prompt(
                    index, page_text, filename, i, total_chunks
                )
                t_chunk = time.perf_counter()
                response = _ollama.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt_for_stats}],
                    options={"temperature": 0, "num_predict": 3000, "think": False},
                )
                chunk_time = time.perf_counter() - t_chunk

                raw = response["message"]["content"]

                # Extract token stats from Ollama response if available
                eval_count = response.get("eval_count", 0)
                prompt_eval_count = response.get("prompt_eval_count", 0)
                eval_duration_ns = response.get("eval_duration", 0)
                total_tokens_in += prompt_eval_count
                total_tokens_out += eval_count
                if eval_duration_ns > 0:
                    tps = eval_count / (eval_duration_ns / 1e9)
                    total_tokens_per_sec_samples.append(tps)

                # Parse the response
                parsed = _parse_ingest_response(raw, filename, today)
                chunk_pages = parsed.get("pages", [])

                if not chunk_pages and "PAGE_START" not in raw and raw.strip() != "NOTHING":
                    chunks_failed_parse += 1
                elif chunk_pages:
                    chunks_with_pages += 1

                # Write pages
                for page in chunk_pages:
                    fm = page["frontmatter"]
                    fname = page.get("filename", "Concepts/Untitled.md")
                    body = page.get("content", "")
                    tags_str = "[" + ", ".join(fm.get("tags", [])) + "]"
                    related_str = "[" + ", ".join(f'"{r}"' for r in fm.get("related", [])) + "]"
                    sources_str = "[" + ", ".join(f'"{s}"' for s in fm.get("sources", [])) + "]"
                    full_content = f"""---
title: "{fm.get('title', fname)}"
tags: {tags_str}
created: "{today}"
updated: "{today}"
sources: {sources_str}
related: {related_str}
---

{body}
"""
                    write_wiki_page(vault_path, fname, full_content)
                    pages_written += 1

                # Update index
                if chunk_pages:
                    index_file = vault_path / "index.md"
                    current_index = index_file.read_text(encoding="utf-8")
                    new_entries = []
                    for page in chunk_pages:
                        fm = page["frontmatter"]
                        entry = f"- [{fm.get('title','Untitled')}]({page.get('filename','')}) — {', '.join(fm.get('tags',[]))}"
                        if page.get("filename") not in current_index:
                            new_entries.append(entry)
                    if new_entries:
                        update_index(vault_path, current_index.rstrip() + "\n" + "\n".join(new_entries) + "\n")

            except Exception as e:
                print(f"  ⚠ Chunk {i} failed: {e}")
                chunks_failed_parse += 1

        total_time = time.perf_counter() - t_start
        avg_tps = sum(total_tokens_per_sec_samples) / len(total_tokens_per_sec_samples) if total_tokens_per_sec_samples else 0.0

        results.append(IngestMetrics(
            model=model,
            source_file=source_file.name,
            total_chunks=total_chunks,
            chunks_with_pages=chunks_with_pages,
            chunks_failed_parse=chunks_failed_parse,
            pages_written=pages_written,
            total_time_sec=round(total_time, 2),
            time_per_chunk_sec=round(total_time / total_chunks, 2) if total_chunks else 0.0,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            tokens_per_sec=round(avg_tps, 1),
        ))

    return results


def _build_ingest_prompt(index, source_text, filename, chunk_num, total_chunks):
    """Build the ingest prompt inline — mirrors what LLM.ingest() does."""
    max_chars = 3000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars] + "\n\n[...truncated...]"

    # Load from Jinja if available, else fall back to the inline template
    try:
        from jinja2 import Environment, FileSystemLoader
        prompts_dir = Path(__file__).parent.parent / "src" / "lokiwiki" / "prompts"
        env = Environment(loader=FileSystemLoader(str(prompts_dir)))
        tmpl = env.get_template("ingest.jinja")
        return tmpl.render(
            index=index, source_text=source_text, filename=filename,
            chunk_num=chunk_num, total_chunks=total_chunks,
        )
    except Exception:
        # Fallback: use the string template from llm.py directly
        from lokiwiki.core.llm import INGEST_PROMPT_TEMPLATE
        return INGEST_PROMPT_TEMPLATE.format(
            index=index, source_text=source_text, filename=filename,
            chunk_num=chunk_num, total_chunks=total_chunks,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Query benchmark
# ─────────────────────────────────────────────────────────────────────────────

def benchmark_queries(
    model: str,
    vault_path: Path,
    questions: list[dict],
    judge_cases: list[JudgeCase]
) -> list[QueryMetrics]:
    """Run all questions against the ingested vault and return per-question metrics."""
    import ollama as _ollama
    from lokiwiki.core.llm import _parse_query_response
    from lokiwiki.core.files import load_wiki_pages

    llm = LLM(model=model)
    results = []
    responses = []
    index = load_index(vault_path)

    for q in questions:
        qid = q["id"]
        question = q["question"]
        print(f"  Query {qid}: {question[:60]}...")

        try:
            # Step 1: find relevant pages
            relevant = llm.find_relevant_pages(index, question)
            if not relevant:
                results.append(QueryMetrics(
                    model=model, question_id=qid, question=question,
                    latency_sec=0.0, answer_length_chars=0,
                    sources_cited=0, citation_accuracy=1.0,
                    answered_or_declined=False,
                    tokens_in=0, tokens_out=0, tokens_per_sec=0.0,
                ))
                continue

            pages_content = load_wiki_pages(vault_path, relevant)

            # Step 2: query with timing
            try:
                from jinja2 import Environment, FileSystemLoader
                prompts_dir = Path(__file__).parent.parent / "src" / "lokiwiki" / "prompts"
                env = Environment(loader=FileSystemLoader(str(prompts_dir)))
                tmpl = env.get_template("query.jinja")
                prompt = tmpl.render(question=question, pages_content=pages_content)
            except Exception:
                from lokiwiki.core.llm import QUERY_PROMPT_TEMPLATE
                prompt = QUERY_PROMPT_TEMPLATE.format(
                    question=question, pages_content=pages_content
                )

            t_start = time.perf_counter()
            response = _ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0, "num_predict": 2000, "think": False},
            )
            latency = time.perf_counter() - t_start

            raw = response["message"]["content"]
            parsed = _parse_query_response(raw)

            answer = parsed.get("answer", "").strip()
            sources = parsed.get("sources", [])

            # Token stats
            eval_count = response.get("eval_count", 0)
            prompt_eval_count = response.get("prompt_eval_count", 0)
            eval_duration_ns = response.get("eval_duration", 0)
            tps = eval_count / (eval_duration_ns / 1e9) if eval_duration_ns > 0 else 0.0

            # Citation accuracy
            citation_acc = check_citation_accuracy(vault_path, sources)

            # answered_or_declined: True if the model gave an answer OR explicitly
            # said it doesn't know (both are valid — hallucinating is not)
            decline_phrases = [
                "not in the wiki", "cannot find", "no information",
                "not available", "don't have", "do not have",
                "i don't know", "i do not know", "not mentioned",
            ]
            is_declined = any(p in answer.lower() for p in decline_phrases)
            answered_or_declined = bool(answer) and (len(answer) > 20 or is_declined)

            results.append(QueryMetrics(
                model=model,
                question_id=qid,
                question=question,
                latency_sec=round(latency, 2),
                answer_length_chars=len(answer),
                sources_cited=len(sources),
                citation_accuracy=round(citation_acc, 3),
                answered_or_declined=answered_or_declined,
                tokens_in=prompt_eval_count,
                tokens_out=eval_count,
                tokens_per_sec=round(tps, 1),
            
            ))
            judge_cases.append(JudgeCase(
                question_id=qid,
                question=question,
                question_type=q.get("type", "unknown"),
                reference_answer=q.get("reference_answer"),
                model=model,
                answer=answer,
                sources_cited=sources,
                wiki_pages_used=pages_content,
            ))

        except Exception as e:
            print(f"  ⚠ Query {qid} failed: {e}")
            results.append(QueryMetrics(
                model=model, question_id=qid, question=question,
                latency_sec=0.0, answer_length_chars=0,
                sources_cited=0, citation_accuracy=0.0,
                answered_or_declined=False,
                tokens_in=0, tokens_out=0, tokens_per_sec=0.0,
            ))
    return results

def write_judge_package(
    judge_cases: list[JudgeCase],
    output_path: Path,
    timestamp: str,
):
    prompts_dir = Path(__file__).parent / "prompts"
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
        env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        judge_prompt = env.get_template("judge.jinja").render()
    except Exception as e:
        raise FileNotFoundError(
            f"Could not load benchmarks/prompts/judge.jinja: {e}"
        )

    package = {
        "meta": {
            "generated": timestamp,
            "total_cases": len(judge_cases),
            "models": list({c.model for c in judge_cases}),
            "instructions": "Upload this file to Claude/ChatGPT/Gemini along with the prompt below. Copy the prompt into the chat first, then attach this file.",
        },
        "judge_prompt": judge_prompt,
        "cases": [asdict(c) for c in judge_cases],
    }

    output_path.write_text(
        json.dumps(package, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"\n  Judge package saved: {output_path}")
    print(f"  → Open your AI assistant of choice")
    print(f"  → Paste the contents of 'judge_prompt' from the file into the chat")
    print(f"  → Attach the entire JSON file")
    print(f"  → Save the response as *_judge_scores.json in benchmarks/results/")
# ─────────────────────────────────────────────────────────────────────────────
# Aggregate & report
# ─────────────────────────────────────────────────────────────────────────────

def compute_summary(
    model: str,
    run: int,
    ingest_results: list[IngestMetrics],
    query_results: list[QueryMetrics],
) -> ModelSummary:
    summary = ModelSummary(model=model, run=run)

    if ingest_results:
        summary.total_ingest_time_sec = round(sum(r.total_time_sec for r in ingest_results), 2)
        total_chunks = sum(r.total_chunks for r in ingest_results)
        total_failures = sum(r.chunks_failed_parse for r in ingest_results)
        summary.total_parse_failures = total_failures
        summary.parse_failure_rate = round(total_failures / total_chunks, 3) if total_chunks else 0.0
        summary.total_pages_written = sum(r.pages_written for r in ingest_results)
        all_tps = [r.tokens_per_sec for r in ingest_results if r.tokens_per_sec > 0]
        summary.avg_ingest_tokens_per_sec = round(sum(all_tps) / len(all_tps), 1) if all_tps else 0.0
        all_chunk_times = [r.time_per_chunk_sec for r in ingest_results if r.time_per_chunk_sec > 0]
        summary.avg_ingest_time_per_chunk_sec = round(sum(all_chunk_times) / len(all_chunk_times), 2) if all_chunk_times else 0.0

    if query_results:
        latencies = [r.latency_sec for r in query_results if r.latency_sec > 0]
        summary.avg_query_latency_sec = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        citation_accs = [r.citation_accuracy for r in query_results]
        summary.avg_citation_accuracy = round(sum(citation_accs) / len(citation_accs), 3)
        summary.queries_answered = sum(1 for r in query_results if r.answered_or_declined)
        qtps = [r.tokens_per_sec for r in query_results if r.tokens_per_sec > 0]
        summary.avg_query_tokens_per_sec = round(sum(qtps) / len(qtps), 1) if qtps else 0.0

    return summary


def save_csv(rows: list[dict], output_path: Path):
    if not rows:
        return
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def render_markdown_table(summaries: list[ModelSummary]) -> str:
    lines = []
    lines.append("# lokiwiki Benchmark Results\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    lines.append("## Summary\n")
    headers = [
        "Model", "Run",
        "Ingest Time (s)", "Time/Chunk (s)", "Pages Written",
        "Parse Failures", "Parse Fail Rate",
        "Ingest tok/s",
        "Avg Query Latency (s)", "Avg Citation Acc", "Queries Answered",
        "Query tok/s",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for s in summaries:
        row = [
            s.model, str(s.run),
            str(s.total_ingest_time_sec),
            str(s.avg_ingest_time_per_chunk_sec),
            str(s.total_pages_written),
            str(s.total_parse_failures),
            f"{s.parse_failure_rate:.1%}",
            str(s.avg_ingest_tokens_per_sec),
            str(s.avg_query_latency_sec),
            f"{s.avg_citation_accuracy:.1%}",
            str(s.queries_answered),
            str(s.avg_query_tokens_per_sec),
        ]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def print_rich_summary(summaries: list[ModelSummary]):
    try:
        from rich.console import Console
        from rich.table import Table
        c = Console()
        t = Table(title="Benchmark Summary", show_lines=True)
        cols = [
            "Model", "Run", "Ingest (s)", "Fail Rate",
            "Pages", "Ingest tok/s",
            "Query (s)", "Citation Acc", "Answered", "Query tok/s"
        ]
        for col in cols:
            t.add_column(col, style="cyan" if col == "Model" else None)
        for s in summaries:
            t.add_row(
                s.model, str(s.run),
                str(s.total_ingest_time_sec),
                f"{s.parse_failure_rate:.1%}",
                str(s.total_pages_written),
                str(s.avg_ingest_tokens_per_sec),
                str(s.avg_query_latency_sec),
                f"{s.avg_citation_accuracy:.1%}",
                str(s.queries_answered),
                str(s.avg_query_tokens_per_sec),
            )
        c.print(t)
    except ImportError:
        # Rich not available — plain print
        for s in summaries:
            print(f"{s.model} run{s.run}: ingest={s.total_ingest_time_sec}s "
                  f"fail_rate={s.parse_failure_rate:.1%} "
                  f"pages={s.total_pages_written} "
                  f"query={s.avg_query_latency_sec}s "
                  f"citation={s.avg_citation_accuracy:.1%}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="lokiwiki Phase 2 Benchmark")
    parser.add_argument("--models", required=True,
                        help="Space-separated model names e.g. 'qwen2.5:7b qwen3.5:9b'")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of runs per model (default: 1)")
    parser.add_argument("--data-dir", default="benchmarks/data",
                        help="Directory containing sample_articles/ and questions.json")
    parser.add_argument("--vault-base", default=None,
                        help="Base dir for throwaway vaults (default: system temp dir)")
    parser.add_argument("--output", default="benchmarks/results",
                        help="Directory to write CSV and Markdown results")
    args = parser.parse_args()

    models = args.models.split()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    sample_dir = data_dir / "sample_articles"
    questions_file = data_dir / "questions.json"

    if not sample_dir.exists() or not any(sample_dir.iterdir()):
        print(f"ERROR: No sample articles found in {sample_dir}")
        print("Add 1-5 PDF/TXT/MD files there before running the benchmark.")
        sys.exit(1)

    if not questions_file.exists():
        print(f"ERROR: questions.json not found at {questions_file}")
        sys.exit(1)

    questions = json.loads(questions_file.read_text(encoding="utf-8"))["questions"]
    today = datetime.now().strftime("%Y-%m-%d")

    vault_base = Path(args.vault_base) if args.vault_base else Path(tempfile.mkdtemp(prefix="lokiwiki_bench_"))
    vault_base.mkdir(parents=True, exist_ok=True)

    all_ingest_rows = []
    all_query_rows = []
    all_summaries = []
    judge_cases = []

    for model in models:
        for run in range(1, args.runs + 1):
            print(f"\n{'='*60}")
            print(f"Model: {model}  Run: {run}/{args.runs}")
            print(f"{'='*60}")

            vault_path = create_fresh_vault(vault_base, model, run)
            source_files = copy_sources_to_raw(vault_path, sample_dir)

            # ── Ingest ────────────────────────────────────────────────
            print("\n[Ingest]")
            ingest_results = benchmark_ingest(model, vault_path, source_files, today)
            for r in ingest_results:
                all_ingest_rows.append(asdict(r))
                print(f"  {r.source_file}: {r.pages_written} pages, "
                      f"{r.chunks_failed_parse}/{r.total_chunks} parse failures, "
                      f"{r.total_time_sec}s")

            # ── Queries ───────────────────────────────────────────────
            print("\n[Queries]")
            query_results = benchmark_queries(model, vault_path, questions,judge_cases)
            for r in query_results:
                all_query_rows.append(asdict(r))
                status = "✓" if r.answered_or_declined else "✗"
                print(f"  {status} {r.question_id}: {r.latency_sec}s "
                      f"citation={r.citation_accuracy:.0%}")

            summary = compute_summary(model, run, ingest_results, query_results)
            all_summaries.append(summary)

            # Clean up vault after each run to save disk space
            shutil.rmtree(vault_path, ignore_errors=True)

    # ── Save results ──────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    model_tag = "_vs_".join(m.replace(":", "_").replace(".", "_") for m in models)

    ingest_csv = output_dir / f"{timestamp}_{model_tag}_ingest.csv"
    query_csv = output_dir / f"{timestamp}_{model_tag}_query.csv"
    summary_md = output_dir / f"{timestamp}_{model_tag}_summary.md"
    summary_csv = output_dir / f"{timestamp}_{model_tag}_summary.csv"

    save_csv(all_ingest_rows, ingest_csv)
    save_csv(all_query_rows, query_csv)
    save_csv([asdict(s) for s in all_summaries], summary_csv)
    summary_md.write_text(render_markdown_table(all_summaries), encoding="utf-8")
    if judge_cases:
        judge_path = output_dir / f"{timestamp}_{model_tag}_judge_package.json"
        write_judge_package(judge_cases, judge_path, timestamp)
    print(f"\n{'='*60}")
    print("Results saved:")
    print(f"  {ingest_csv}")
    print(f"  {query_csv}")
    print(f"  {summary_csv}")
    print(f"  {summary_md}")
    print()
    print_rich_summary(all_summaries)


if __name__ == "__main__":
    main()
