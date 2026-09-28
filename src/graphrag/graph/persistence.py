import json
from pathlib import Path

import networkx as nx


def save_graph(graph: nx.MultiDiGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(graph, edges="links")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_graph(path: Path) -> nx.MultiDiGraph:
    if not path.exists():
        return nx.MultiDiGraph()
    data = json.loads(path.read_text(encoding="utf-8"))
    return nx.node_link_graph(data, directed=True, multigraph=True, edges="links")


def save_meta(meta: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def load_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def export_graphml(graph: nx.MultiDiGraph) -> str:
    # MultiDiGraph → DiGraph（GraphML 对平行边支持弱，按 key 合并为多条路径）
    simple = nx.MultiDiGraph(graph)
    import io

    buf = io.StringIO()
    nx.write_graphml(simple, buf)
    return buf.getvalue()
