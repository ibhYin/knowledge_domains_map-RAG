"""来源重排序：把与问题最相关的分块排到上下文窗口前排。

候选来自 2 跳图扩张（可达百余块），collect_sources 按 chunk_id 字典序返回，
与相关性无关；答案生成只取前 max_answer_sources 块，金标分块常被截掉
（"证据在库不在窗"）。本模块用零依赖的 BM25（CJK 字符二元组）加实体/
种子锚定加分重排，只调整列表顺序、不重新编号，引用与校验逻辑不受影响。

评分 = BM25(问题词元, 分块全文) + 命中实体数 * ENTITY_BONUS + 种子锚定 * SEED_BONUS
"""

import math
import re

from graphrag.graph.entity_resolver import normalize

# 加分权重：实体名出现在分块正文中（按去重实体数计）；种子节点证据分块。
# 经金标排名诊断校准（evals/diagnose_rank.py），目标是金标块稳定进前 10。
ENTITY_BONUS = 2.0
SEED_BONUS = 1.5

_K1 = 1.5
_B = 0.75

_ASCII_WORD = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def query_terms(text: str) -> frozenset[str]:
    """问题词元：ASCII 完整单词 + CJK 字符二元组（单字段取单字）。"""
    s = normalize(text)
    if not s:
        return frozenset()
    terms = {f"w:{w}" for w in _ASCII_WORD.findall(s)}
    for run in _CJK_RUN.findall(s):
        if len(run) == 1:
            terms.add(run)
            continue
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return frozenset(terms)


def _doc_terms(content: str) -> frozenset[str]:
    return query_terms(content)


def rerank_sources(
    question: str,
    sources: list[dict],
    entity_names: list[str] | None = None,
    seed_chunk_ids: frozenset[str] | set[str] = frozenset(),
) -> list[dict]:
    """返回按相关性降序的新列表；并列时保持原有相对顺序（稳定排序）。

    只重排不重新编号：source 的 id 字段随 dict 走，draft/verifier 的
    引用编号、逐字校验与 history 快照语义均不变。
    """
    if not sources:
        return list(sources)
    q_terms = query_terms(question)
    if not q_terms:
        return list(sources)

    doc_terms = [_doc_terms(s.get("content", "")) for s in sources]
    lengths = [len(t) or 1 for t in doc_terms]
    avg_len = sum(lengths) / len(lengths)
    n_docs = len(sources)

    df: dict[str, int] = {}
    for terms in doc_terms:
        for t in q_terms & terms:
            df[t] = df.get(t, 0) + 1

    entity_names = [normalize(n) for n in (entity_names or []) if normalize(n)]
    bm25 = []
    for terms, length in zip(doc_terms, lengths):
        score = 0.0
        for t in q_terms & terms:
            idf = math.log((n_docs - df[t] + 0.5) / (df[t] + 0.5) + 1.0)
            tf = 1.0  # 词元集合已去重；二元组多次出现对短问题贡献有限，按出现与否计
            score += idf * tf * (_K1 + 1) / (tf + _K1 * (1 - _B + _B * length / avg_len))
        bm25.append(score)

    def boost(index: int) -> float:
        score = bm25[index]
        if entity_names:
            content = normalize(sources[index].get("content", ""))
            score += ENTITY_BONUS * sum(1 for n in entity_names if n and n in content)
        if sources[index].get("chunk_id") in seed_chunk_ids:
            score += SEED_BONUS
        return score

    # sorted(reverse=True) 仍是稳定排序：并列分保持原有相对顺序
    order = sorted(range(len(sources)), key=boost, reverse=True)
    return [sources[i] for i in order]
