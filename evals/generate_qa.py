"""从语料分块合成问答评测集（回归集，非基准真相）。

每篇文档取前 N 个分块，按类型模板轮换出题（单跳事实/实体关系/时间/
否定边界），模型输出 gold_answer + 依据句 quote + seed_entities；
防循环校验：quote 必须是分块原文的逐字子串，不合格重试一次后丢弃。
输出 JSONL：{"question", "gold_answer", "gold_chunks", "gold_quotes",
"seed_entities", "qtype", "source"}。

运行：PYTHONPATH=src python evals/generate_qa.py [--per-doc 2] [--limit-docs 30]
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graphrag.config import settings  # noqa: E402
from graphrag.llm.client import build_llm  # noqa: E402
from graphrag.pipeline.chunk_store import ChunkStore, chunk_id_of  # noqa: E402
from graphrag.schemas.extraction import ChunkExtraction  # noqa: E402

QTYPE_ROTATION = ["single_hop", "relation", "temporal", "negative"]

PROMPT = """你是评测集标注员。根据给定文本片段出 1 道中文问答评测题，类型为：{qtype_desc}。

要求：
1. 问题不得照抄原文整句，答案必须完全由片段内容支撑，不要引入片段外知识。
2. gold_answer：一句中文标准答案。
3. gold_quotes：支撑答案的原文片段，必须逐字复制原文连续文字（可多句，每条 20-80 字）。
4. seed_entities：问题中提到的实体名（需在片段中出现），1-2 个。
5. {extra_rule}
只输出 JSON：
{{"question": "...", "gold_answer": "...", "gold_quotes": ["..."], "seed_entities": ["..."]}}"""

QTYPE_DESC = {
    "single_hop": "单跳事实题——问一个明确事实（是什么/定义/数量/归属）",
    "relation": "实体关系题——问两个实体之间的关系（谁做了什么/位于哪/参与了什么）",
    "temporal": "时间题——答案必须包含具体年份或时期",
    "negative": "否定边界题——问一个文本没有提及、无法从文本回答的问题，gold_answer 填「文本未提及，无法回答」",
}

NEGATIVE_ANSWER = "文本未提及，无法回答"


def _parse_json(raw: str):
    import re

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def generate_one(llm, qtype: str, chunk_text: str) -> dict | None:
    desc = QTYPE_DESC[qtype]
    extra = ("gold_quotes 填空数组 []。" if qtype == "negative"
             else "gold_quotes 里每条都必须逐字来自原文。")
    prompt = PROMPT.format(qtype_desc=desc, extra_rule=extra)
    text = chunk_text[:1600]
    for _ in range(2):  # 解析/校验失败重试一次
        try:
            result = llm.invoke([{"role": "system", "content": prompt},
                                 {"role": "user", "content": f"文本片段：\n{text}"}])
        except Exception as exc:  # noqa: BLE001
            print(f"  模型调用失败: {type(exc).__name__}")
            return None
        data = _parse_json(result.content)
        if not data or not data.get("question") or not data.get("gold_answer"):
            continue
        quotes = [q for q in (data.get("gold_quotes") or []) if isinstance(q, str) and q.strip()]
        if qtype != "negative":
            # 防循环：依据句必须逐字来自原文
            if not quotes or not all(q in chunk_text for q in quotes):
                continue
        seeds = [s for s in (data.get("seed_entities") or []) if isinstance(s, str) and s.strip()]
        if qtype != "negative" and not seeds:
            continue
        answer = data["gold_answer"].strip()
        if qtype == "negative":
            quotes = []
        return {"question": data["question"].strip(), "gold_answer": answer,
                "gold_quotes": quotes, "seed_entities": seeds, "qtype": qtype}
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-doc", type=int, default=2, help="每篇文档取前几个分块出题")
    parser.add_argument("--limit-docs", type=int, default=30, help="取前多少篇文档")
    parser.add_argument("--out", default=str(settings.data_dir / "evals" / "synthetic.jsonl"))
    args = parser.parse_args()

    chunks = ChunkStore().iter_chunks()
    by_doc: dict[str, list[dict]] = {}
    for record in chunks:
        doc_id = record["metadata"]["doc_id"]
        by_doc.setdefault(doc_id, []).append(record)

    docs = sorted(by_doc)[:args.limit_docs]
    llm = build_llm(temperature=0.3)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    with out_path.open("w", encoding="utf-8") as out:
        for doc_id in docs:
            records = sorted(by_doc[doc_id], key=lambda r: r["chunk_index"])[:args.per_doc]
            for i, record in enumerate(records):
                qtype = QTYPE_ROTATION[i % len(QTYPE_ROTATION)]
                cid = chunk_id_of(doc_id, record["chunk_index"])
                item = generate_one(llm, qtype, record["content"])
                if item is None:
                    skipped += 1
                    continue
                item["gold_chunks"] = [cid]
                item["source"] = "synthetic"
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                written += 1
                print(f"  [{written}] ({qtype}) {item['question'][:44]}")
    print(f"完成：生成 {written} 题，跳过 {skipped} 题 → {out_path}")


if __name__ == "__main__":
    main()
