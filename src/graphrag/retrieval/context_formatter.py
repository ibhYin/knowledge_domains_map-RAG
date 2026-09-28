from typing import Iterable

from graphrag.graph.store import GraphStore
from graphrag.schemas.extraction import ENTITY_TYPE_CN, RELATION_TYPE_CN


def _doc_ids(source_chunks: Iterable[str]) -> list[str]:
    seen = []
    for cid in source_chunks:
        doc_id = str(cid).split(":", 1)[0]
        if doc_id not in seen:
            seen.append(doc_id)
    return seen


def format_subgraph_context(
    store: GraphStore,
    subgraph,
    edges: list,
    question: str,
) -> str:
    lines = []
    sub_nodes = list(subgraph.nodes)
    nodes_sorted = sorted(
        sub_nodes,
        key=lambda n: subgraph.nodes[n].get("mention_count", 0),
        reverse=True,
    )
    lines.append(f"【图谱检索到的实体】（共 {len(nodes_sorted)} 个）")
    for n in nodes_sorted:
        data = subgraph.nodes[n]
        type_cn = ENTITY_TYPE_CN.get(data.get("type"), data.get("type", "未知"))
        desc = data.get("description", "") or "（无描述）"
        count = data.get("mention_count", 0)
        docs = "、".join(_doc_ids(data.get("source_chunks", [])))
        lines.append(f"- {data.get('name', n)}（{type_cn}）：{desc}（出现 {count} 次；来源：{docs or '未知'}）")

    lines.append(f"\n【实体间关系】（共 {len(edges)} 条）")
    for u, v, key, data in edges:
        rel_cn = RELATION_TYPE_CN.get(key, key)
        desc = data.get("description", "")
        docs = "、".join(_doc_ids(data.get("source_chunks", [])))
        suffix = f"，{desc}" if desc else ""
        lines.append(f"- {subgraph.nodes[u].get('name', u)} --{rel_cn}--> {subgraph.nodes[v].get('name', v)}{suffix}（来源：{docs or '未知'}）")

    lines.append(f"\n【问题】{question}")
    lines.append("\n【回答要求】")
    lines.append("1. 只依据上述图谱上下文回答，用中文、结构清晰。")
    lines.append("2. 引用事实时注明涉及的相关实体名。")
    lines.append("3. 若图谱内容不足以回答问题，直接说明缺少哪些信息，不要编造。")
    return "\n".join(lines)
