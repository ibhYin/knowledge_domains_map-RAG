"""生成手工金标 20 题 → evals/gold/wiki_gold.jsonl（含逐字 quote 校验）。

每题 gold_quotes 必须是对应 gold_chunks 分块原文的逐字子串，
seed_entities 必须在题面中出现且在分块中出现，否则拒绝写入。
运行：PYTHONPATH=src python evals/gold/build_gold.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from graphrag.pipeline.chunk_store import chunk_id_of  # noqa: E402

NEGATIVE_ANSWER = "文本未提及，无法回答"

ITEMS = [
    # ---- event（4）----
    dict(
        question="《南京条约》是清朝在哪一年签订的？",
        gold_answer="1842年（道光二十二年）。",
        gold_quotes=["道光二十二年（1842年），清朝在對大英帝国的第一次鸦片战争中战败"],
        seed_entities=["第一次鴉片戰爭"],
        qtype="temporal", doc="49197c6b749f", chunk_index=1,
    ),
    dict(
        question="五四运动中学生们抗议的是哪次会议上有关山东问题的决议？",
        gold_answer="巴黎和会。",
        gold_quotes=["1919年5月4日，北京的學生游行示威，抗議巴黎和會上有關山東問題的決議"],
        seed_entities=["巴黎和會"],
        qtype="single_hop", doc="45c1b790bf4e", chunk_index=1,
    ),
    dict(
        question="改革开放是由谁提出、在哪次会议后正式实施的？",
        gold_answer="由以邓小平为核心的中国共产党第二代中央领导集体提出，在1978年12月中共十一届三中全会后正式实施。",
        gold_quotes=["改革开放，是指由以邓小平为核心的中国共产党第二代中央领导集体等人提出和创立，"
                     "在1978年12月18日中共十一届三中全会后开始正式实施"],
        seed_entities=["邓小平"],
        qtype="relation", doc="1054aa935139", chunk_index=1,
    ),
    dict(
        question="郑和七次下西洋总共耗费了多少白银？",
        gold_answer=NEGATIVE_ANSWER,
        gold_quotes=[],
        seed_entities=["郑和"],
        qtype="negative", doc="8f9394a5d689", chunk_index=1,
    ),
    # ---- geo（4）----
    dict(
        question="长江全长多少公里，是世界第几长河？",
        gold_answer="全长6300公里，是亚洲第一长河、世界第三长河。",
        gold_quotes=["是亚洲第一长河和世界第三长河，也是世界上完全在一国境内的最长河流，全长6300公里"],
        seed_entities=["长江"],
        qtype="single_hop", doc="a36a6f9ad42a", chunk_index=1,
    ),
    dict(
        question="北京背靠哪座山脉、位于什么平原的北部边缘？",
        gold_answer="背靠燕山，位于华北平原的北部边缘。",
        gold_quotes=["北京位於華北平原的北部边缘，背靠燕山，毗邻天津市、河北省"],
        seed_entities=["北京市"],
        qtype="relation", doc="996369b481e9", chunk_index=1,
    ),
    dict(
        question="西湖位于哪个城市的什么方位？",
        gold_answer="位于浙江省杭州旧城西侧。",
        gold_quotes=["西湖位于中华人民共和国浙江省杭州旧城西侧"],
        seed_entities=["西湖"],
        qtype="single_hop", doc="d4ad54416a2a", chunk_index=1,
    ),
    dict(
        question="青藏高原的冰川总储量大约是多少立方米？",
        gold_answer=NEGATIVE_ANSWER,
        gold_quotes=[],
        seed_entities=["青藏高原"],
        qtype="negative", doc="2049ab99b134", chunk_index=1,
    ),
    # ---- general（3）----
    dict(
        question="世界上最早的气象书籍是什么？",
        gold_answer="古希腊哲学家亚里士多德的《气象汇论》。",
        gold_quotes=["第一位建立氣象學的人是古希臘哲學家亞里士多德。在他的專書《氣象匯論》中，"
                     "他最先敘述和粗淺地解釋了風、雲、雨、雪、雷、雹等天氣現象，而這書是世界上最早的氣象書籍"],
        seed_entities=["气象学"],
        qtype="single_hop", doc="c5a64bf8a631", chunk_index=1,
    ),
    dict(
        question="牛顿因提出三大运动定律获得了哪一年的诺贝尔奖？",
        gold_answer=NEGATIVE_ANSWER,
        gold_quotes=[],
        seed_entities=["力学", "牛顿"],
        qtype="negative", doc="d48908ee4dc1", chunk_index=1,
    ),
    dict(
        question="开启现代科学海洋学的是哪次远征？",
        gold_answer="1872-76年的挑战者号远征。",
        gold_quotes=["開啟現代科學海洋學的是1872-76年的挑戰者號遠征"],
        seed_entities=["海洋学"],
        qtype="single_hop", doc="83d9d605be8e", chunk_index=1,
    ),
    # ---- org（3）----
    dict(
        question="清华大学始建于哪一年？",
        gold_answer="1911年。",
        gold_quotes=["始建于1911年，因北京西北郊清华园而得名"],
        seed_entities=["清华大学"],
        qtype="temporal", doc="9e629dbc7531", chunk_index=1,
    ),
    dict(
        question="中国科学院是何时、在哪里成立的？",
        gold_answer="1949年11月在北京成立。",
        gold_quotes=["中国科学院是中华人民共和国科学技术方面的最高学术机构，为国务院直属事业单位，於1949年11月在北京成立"],
        seed_entities=["中国科学院"],
        qtype="temporal", doc="66297f3fdcd1", chunk_index=1,
    ),
    dict(
        question="腾讯的总部位于哪里？",
        gold_answer="深圳南山区腾讯滨海大厦。",
        gold_quotes=["總部位於深圳南山区騰訊濱海大廈"],
        seed_entities=["腾讯"],
        qtype="single_hop", doc="d837c303e97d", chunk_index=1,
    ),
    # ---- person（3）----
    dict(
        question="李白与哪位诗人一起被认定为盛唐最伟大的诗人？",
        gold_answer="杜甫。",
        gold_quotes=["李白與杜甫一起自九世紀初就被認定是盛唐最偉大的詩人"],
        seed_entities=["李白"],
        qtype="relation", doc="009a46aa31c1", chunk_index=1,
    ),
    dict(
        question="苏轼的号是什么？",
        gold_answer="东坡居士（又号铁冠道人）。",
        gold_quotes=["字子瞻，一字和仲，号东坡居士、鐵冠道人"],
        seed_entities=["苏轼"],
        qtype="single_hop", doc="53bf134250f7", chunk_index=1,
    ),
    dict(
        question="岳飞的词作《满江红·写怀》创作于哪一年？",
        gold_answer=NEGATIVE_ANSWER,
        gold_quotes=[],
        seed_entities=["岳飛"],
        qtype="negative", doc="024ecc5b5e99", chunk_index=1,
    ),
    # ---- tech（3）----
    dict(
        question="活字印刷术的发明者是谁？",
        gold_answer="北宋的毕昇。",
        gold_quotes=["大約在1045年，畢昇發明了膠泥活字印刷術，用以取代雕版印刷術"],
        seed_entities=["活字印刷術"],
        qtype="relation", doc="03a365a6d207", chunk_index=1,
    ),
    dict(
        question="传说中蔡伦在哪一年发明了纸？",
        gold_answer="公元105年左右。",
        gold_quotes=["据说在公元105年左右用桑树皮和其他韧皮纤维以及渔网、旧布和麻废料发明了纸"],
        seed_entities=["蔡伦"],
        qtype="temporal", doc="f5c3ad79e4f8", chunk_index=2,
    ),
    dict(
        question="学术界一般认为火药发明于什么时候的哪个国家？",
        gold_answer="9世纪的中国。",
        gold_quotes=["学术界一般认为火药发明于9世纪的中国，为当时中国术士炼制长生不老药时意外得到的副产品"],
        seed_entities=["火藥"],
        qtype="single_hop", doc="347e718fcc93", chunk_index=1,
    ),
]


def main() -> None:
    out = ROOT / "evals" / "gold" / "wiki_gold.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    chunks_cache: dict[str, dict[int, str]] = {}

    def chunk_text(doc: str, index: int) -> str:
        if doc not in chunks_cache:
            lines = (ROOT / "data" / "chunks" / f"{doc}.jsonl").read_text(encoding="utf-8").splitlines()
            chunks_cache[doc] = {r["chunk_index"]: r["content"] for r in map(json.loads, lines)}
        return chunks_cache[doc][index]

    errors = []
    rows = []
    for i, item in enumerate(ITEMS, 1):
        doc, idx = item["doc"], item["chunk_index"]
        cid = chunk_id_of(doc, idx)
        text = chunk_text(doc, idx)
        for q in item["gold_quotes"]:
            if q not in text:
                errors.append(f"[{i}] {item['question'][:20]} quote 不在分块 {cid} 原文中: {q[:40]}…")
        for seed in item["seed_entities"]:
            if seed not in text:
                errors.append(f"[{i}] seed {seed} 不在分块 {cid} 原文中")
        if item["qtype"] != "negative" and not item["gold_quotes"]:
            errors.append(f"[{i}] 非否定题缺少 gold_quotes")
        rows.append({
            "question": item["question"], "gold_answer": item["gold_answer"],
            "gold_quotes": item["gold_quotes"], "seed_entities": item["seed_entities"],
            "qtype": item["qtype"], "gold_chunks": [cid], "source": "gold",
        })

    if errors:
        print("\n".join(errors))
        sys.exit(1)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    stats: dict[str, int] = {}
    for r in rows:
        stats[r["qtype"]] = stats.get(r["qtype"], 0) + 1
    print(f"写入 {len(rows)} 题 → {out}")
    print("题型分布:", stats)


if __name__ == "__main__":
    main()
