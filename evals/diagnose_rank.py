"""金标分块检索排名诊断（零 LLM 调用，秒级）。

对每道金标题用 seed_override 走完整检索链（图扩张 → collect_sources），
记录金标分块在候选列表中的排名：before = 重排前（chunk_id 字典序），
after = rerank_sources 重排后。用于校准重排权重与量化瓶颈②
（"证据在库不在窗"：金标块排名远超喂给模型的分块上限）。

运行：PYTHONPATH=src python evals/diagnose_rank.py [--out docs/benchmarks/rank_diagnosis.json]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graphrag.pipeline.service import service  # noqa: E402
from graphrag.retrieval.evidence import collect_sources  # noqa: E402


def diagnose_one(item: dict, max_answer_sources: int) -> dict:
    search = service.search.search(item["question"], seed_override=item["seed_entities"])
    documents = service.list_documents()
    records = service.chunks.iter_chunks([d["doc_id"] for d in documents])
    sources = collect_sources(documents, records, search["subgraph"], search["edges"])
    gold = set(item["gold_chunks"])

    def ranks(order: list[dict]) -> int | None:
        ids = [s["chunk_id"] for s in order]
        hits = [i + 1 for i, cid in enumerate(ids) if cid in gold]
        return min(hits) if hits else None

    before = ranks(sources)
    # 重排（与 service.answer 相同输入）
    from graphrag.retrieval.rerank import rerank_sources

    entity_names = [m["name"] for m in search["matched_entities"]] + \
                   [m["query"] for m in search["matched_entities"]]
    seed_cids: set[str] = set()
    for m in search["matched_entities"]:
        node = service.store.G.nodes.get(m["node"])
        seed_cids.update(node.get("source_chunks", []) or [])
    reranked = rerank_sources(item["question"], sources, entity_names, seed_cids)
    after = ranks(reranked)

    seed_hit = bool(search["matched_entities"])
    return {
        "question": item["question"],
        "qtype": item["qtype"],
        "seed_hit": seed_hit,
        "n_candidates": len(sources),
        "rank_before": before,
        "rank_after": after,
        "in_window_before": before is not None and before <= max_answer_sources,
        "in_window_after": after is not None and after <= max_answer_sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(ROOT / "evals" / "gold" / "wiki_gold.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "docs" / "benchmarks" / "rank_diagnosis.json"))
    parser.add_argument("--max-answer-sources", type=int, default=None,
                        help="窗口上限（默认读 settings.max_answer_sources）")
    args = parser.parse_args()

    from graphrag.config import settings

    max_answer_sources = args.max_answer_sources or settings.max_answer_sources
    service.load()
    items = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]

    rows = []
    for item in items:
        if item["qtype"] == "negative":
            continue  # 否定题无金标分块，不参与排名统计
        rows.append(diagnose_one(item, max_answer_sources))
        r = rows[-1]
        print(f"[{len(rows)}/{len([i for i in items if i['qtype'] != 'negative'])}] "
              f"before={r['rank_before']} after={r['rank_after']}/{r['n_candidates']} "
              f"{'seed_miss' if not r['seed_hit'] else ''} {r['question'][:26]}")

    valid = [r for r in rows if r["rank_before"] is not None]
    summary = {
        "max_answer_sources": max_answer_sources,
        "n_questions": len(rows),
        "gold_found_before": len(valid),
        "gold_found_after": len([r for r in rows if r["rank_after"] is not None]),
        "mean_rank_before": round(sum(r["rank_before"] for r in valid) / len(valid), 1) if valid else None,
        "mean_rank_after": round(sum(r["rank_after"] for r in rows if r["rank_after"] is not None) /
                                 max(1, len([r for r in rows if r["rank_after"] is not None])), 1),
        "in_window_rate_before": round(sum(r["in_window_before"] for r in rows) / len(rows), 4),
        "in_window_rate_after": round(sum(r["in_window_after"] for r in rows) / len(rows), 4),
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n窗口上限 {max_answer_sources}：进窗率 before={summary['in_window_rate_before']} "
          f"after={summary['in_window_rate_after']}；平均排名 before={summary['mean_rank_before']} "
          f"after={summary['mean_rank_after']}")
    print(f"写入 {out}")


if __name__ == "__main__":
    main()
