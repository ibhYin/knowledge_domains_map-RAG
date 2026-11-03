"""评测运行器：问答对数据集 → service.answer → 质量与性能报告。

质量指标（按题可得性分别平均）：
- 来源召回率 recall：金标分块被检索到的比例（gold_chunks ∩ retrieved / gold_chunks）
- 引用正确率 citation_precision：被引分块属于金标分块的比例
- 忠实度 faithfulness：verification == verified 的比例；并独立复跑逐字 quote 校验
- 否定题诚实拒答率：negative 题正确返回「无法回答/证据不足」的比例
- 种子定位率（full 模式）：问题实体在图谱中命中的比例

性能指标：端到端延迟 p50/p95/max（ms）、retrieval/sources/llm 分段耗时。

运行：PYTHONPATH=src python evals/run_eval.py evals/gold/wiki_gold.jsonl --mode seed
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graphrag.pipeline.service import service  # noqa: E402


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]


def quote_check(result: dict) -> bool:
    """独立复跑逐字引用校验：每个被引句的 quote 必须是对应来源分块的子串。"""
    lookup = {s["chunk_id"]: s for s in result.get("sources", [])}
    for sentence in result.get("sentences", []):
        for c in sentence.get("citations", []):
            src = lookup.get(c["source_id"])
            if src is None or not c.get("quote") or c["quote"] not in src["content"]:
                return False
    return True


def evaluate_item(item: dict, result: dict, mode: str) -> dict:
    gold_chunks = set(item.get("gold_chunks") or [])
    retrieved = {s["chunk_id"] for s in (result.get("sources") or []) + (result.get("retrieved_sources") or [])}
    cited = {s["chunk_id"] for s in result.get("sources") or []}
    row = {
        "question": item["question"],
        "qtype": item.get("qtype", "unknown"),
        "mode": mode,
        "verification": result.get("verification"),
        "quote_exact": quote_check(result),
        "latency_ms": round(sum(result.get("timings", {}).values()), 1),
        "timings": result.get("timings", {}),
    }
    if item.get("qtype") == "negative":
        refused = (result.get("verification") == "insufficient"
                   or ("不足" in result.get("answer", "") or "未提及" in result.get("answer", "")
                       or "无法回答" in result.get("answer", "")))
        row["honest_refusal"] = refused
    else:
        if gold_chunks:
            row["recall"] = len(gold_chunks & retrieved) / len(gold_chunks)
            row["citation_precision"] = (len(cited & gold_chunks) / len(cited)) if cited else 0.0
        if mode == "full":
            row["seed_hit"] = bool(result.get("matched_entities"))
    return row


def aggregate(rows: list[dict]) -> dict:
    def mean(key: str) -> float | None:
        values = [r[key] for r in rows if key in r]
        return round(sum(values) / len(values), 4) if values else None

    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms")]
    neg = [r for r in rows if r["qtype"] == "negative"]
    pos = [r for r in rows if r["qtype"] != "negative"]
    summary = {
        "n_questions": len(rows),
        "recall": mean("recall"),
        "citation_precision": mean("citation_precision"),
        "faithful_rate": round(sum(1 for r in rows if r.get("verification") == "verified") / len(rows), 4) if rows else None,
        "quote_exact_rate": round(sum(1 for r in rows if r.get("quote_exact")) / len(rows), 4) if rows else None,
        "honest_refusal_rate": round(sum(1 for r in neg if r.get("honest_refusal")) / len(neg), 4) if neg else None,
        "seed_hit_rate": mean("seed_hit") if any("seed_hit" in r for r in rows) else None,
        "latency_p50_ms": round(percentile(latencies, 50), 1),
        "latency_p95_ms": round(percentile(latencies, 95), 1),
        "latency_max_ms": round(max(latencies), 1) if latencies else None,
        "retrieval_ms_avg": round(sum(r["timings"].get("retrieval_ms", 0) for r in rows) / len(rows), 1) if rows else None,
        "llm_ms_avg": round(sum(r["timings"].get("llm_ms", 0) for r in rows) / len(rows), 1) if rows else None,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="评测集 JSONL 路径")
    parser.add_argument("--mode", choices=["seed", "full"], default="seed")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全部）")
    parser.add_argument("--tag", default="", help="报告文件名标签")
    parser.add_argument("--report-dir", default=str(Path(ROOT) / "data" / "evals"))
    args = parser.parse_args()

    items = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        items = items[:args.limit]
    print(f"评测集 {args.dataset}：{len(items)} 题，模式 {args.mode}\n")

    rows = []
    started = time.monotonic()
    for i, item in enumerate(items, 1):
        seeds = item.get("seed_entities") if args.mode == "seed" else None
        try:
            result = service.answer(item["question"], seed_override=seeds)
            row = evaluate_item(item, result, args.mode)
        except Exception as exc:  # noqa: BLE001
            row = {"question": item["question"], "qtype": item.get("qtype"), "mode": args.mode,
                   "error": f"{type(exc).__name__}: {exc}", "latency_ms": 0.0, "timings": {}}
        rows.append(row)
        detail = (f"recall={row.get('recall', '-')}" if "recall" in row
                  else ("拒答" if row.get("honest_refusal") else "误答") if row["qtype"] == "negative"
                  else row.get("verification", "?"))
        print(f"[{i}/{len(items)}] {row['question'][:36]} -> {detail} ({row.get('latency_ms', 0):.0f}ms)")

    summary = aggregate(rows)
    elapsed = time.monotonic() - started
    report = {
        "dataset": args.dataset, "mode": args.mode, "elapsed_s": round(elapsed, 1),
        "summary": summary, "rows": rows,
        "graph": {**service.store.stats()},
    }
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    tag = args.tag or Path(args.dataset).stem
    out = report_dir / f"report_{tag}_{args.mode}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n========== 摘要 ==========")
    print(f"| 指标 | 数值 |\n|---|---|")
    label = {"recall": "来源召回率", "citation_precision": "引用正确率",
             "faithful_rate": "忠实度(verified 比例)", "quote_exact_rate": "逐字引用校验通过率",
             "honest_refusal_rate": "否定题诚实拒答率", "seed_hit_rate": "种子定位率",
             "latency_p50_ms": "延迟 p50 (ms)", "latency_p95_ms": "延迟 p95 (ms)",
             "latency_max_ms": "延迟 max (ms)"}
    for key, name in label.items():
        if summary.get(key) is not None:
            print(f"| {name} | {summary[key]} |")
    print(f"\n报告写入 {out}")


if __name__ == "__main__":
    main()
