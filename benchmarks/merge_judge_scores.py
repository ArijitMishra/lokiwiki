"""
After uploading the judge package to an AI assistant and saving the response,
run this to merge the scores into your benchmark summary CSV.

Usage:
    python benchmarks/merge_judge_scores.py \
        --scores benchmarks/results/2026-04-24_scores.json \
        --summary benchmarks/results/2026-04-24_summary.csv
"""
import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    scores = json.loads(Path(args.scores).read_text(encoding="utf-8"))

    # Aggregate per model
    model_scores = defaultdict(lambda: {"faithfulness": [], "relevance": [], "completeness": []})
    for entry in scores:
        m = entry["model"]
        model_scores[m]["faithfulness"].append(entry["faithfulness"])
        model_scores[m]["relevance"].append(entry["relevance"])
        model_scores[m]["completeness"].append(entry["completeness"])

    # Print summary
    print(f"\n{'Model':<20} {'Faithfulness':>14} {'Relevance':>10} {'Completeness':>13} {'Overall':>8}")
    print("-" * 70)
    for model, s in model_scores.items():
        f = sum(s["faithfulness"]) / len(s["faithfulness"])
        r = sum(s["relevance"]) / len(s["relevance"])
        c = sum(s["completeness"]) / len(s["completeness"])
        overall = (f + r + c) / 3
        print(f"{model:<20} {f:>14.1f} {r:>10.1f} {c:>13.1f} {overall:>8.1f}")

    # Optionally append to summary CSV
    summary_path = Path(args.summary)
    if summary_path.exists():
        rows = list(csv.DictReader(summary_path.open(encoding="utf-8")))
        for row in rows:
            m = row.get("model")
            if m in model_scores:
                s = model_scores[m]
                row["judge_faithfulness"] = round(sum(s["faithfulness"]) / len(s["faithfulness"]), 2)
                row["judge_relevance"] = round(sum(s["relevance"]) / len(s["relevance"]), 2)
                row["judge_completeness"] = round(sum(s["completeness"]) / len(s["completeness"]), 2)
                row["judge_overall"] = round(
                    (row["judge_faithfulness"] + row["judge_relevance"] + row["judge_completeness"]) / 3, 2
                )
        fieldnames = list(rows[0].keys())
        with summary_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nScores merged into {summary_path}")

if __name__ == "__main__":
    main()