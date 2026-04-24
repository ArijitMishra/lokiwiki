# lokiwiki Benchmarks

Phase 2 benchmark suite — measures ingest time, query latency, tokens/sec, citation accuracy, and parse failure rate. No LLM judge required.

## Setup

### 1. Add sample articles

Drop 3–5 real files (PDF, TXT, or MD) that you actually use into:

```
benchmarks/data/sample_articles/
```

Use articles you care about — the benchmark is most useful when it reflects your real workload. Obsidian Web Clipper exports work well here.

### 2. Fill in questions.json

Open `benchmarks/data/questions.json` and replace all `"FILL IN"` reference answers with real answers based on your sample articles. The questions themselves are pre-written — you only need to fill in the `reference_answer` fields for q01–q06.

### 3. Run the benchmark

```bash
# Compare two models, one run each
python benchmarks/benchmark.py \
    --models "qwen2.5:7b qwen3.5:9b" \
    --runs 1 \
    --data-dir benchmarks/data \
    --output benchmarks/results

# Three runs per model for more stable averages
python benchmarks/benchmark.py \
    --models "qwen2.5:7b qwen3.5:9b" \
    --runs 3 \
    --output benchmarks/results
```

### 4. Read the results

Results are written to `benchmarks/results/` as:
- `*_summary.md` — Markdown table, paste into your notes
- `*_summary.csv` — aggregated per-model metrics
- `*_ingest.csv` — per-file ingest details
- `*_query.csv` — per-question query details

## Metrics explained

| Metric | What it tells you |
|---|---|
| **Ingest Time (s)** | Total wall time to process all sample articles |
| **Time/Chunk (s)** | Average time per page/chunk — affects how long big PDFs take |
| **Pages Written** | How many wiki pages the model created — more is generally better |
| **Parse Fail Rate** | % of chunks that returned no `PAGE_START` block — lower is better, 0% is ideal |
| **Ingest tok/s** | Raw generation speed during ingest |
| **Avg Query Latency (s)** | How long each question takes end-to-end |
| **Avg Citation Accuracy** | % of cited `[[pages]]` that actually exist on disk — measures hallucinated links |
| **Queries Answered** | How many questions got a real answer or an explicit "I don't know" |
| **Query tok/s** | Raw generation speed during query |

## What to look for

**Parse Fail Rate > 10%** means the model is not following the `PAGE_START...PAGE_END` format reliably. Don't use that model for ingest.

**Citation Accuracy < 80%** means the model is hallucinating page names that don't exist. Your Obsidian graph will have lots of broken links.

**Pages Written = 0** after ingest means everything failed — check Ollama is running and the model name is correct.

## Stability note

Run with `--runs 3` before making a final model decision. A single run can vary by 20–30% on latency depending on system load and model cache state.
