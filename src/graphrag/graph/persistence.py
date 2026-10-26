import json
import os
import tempfile
from itertools import chain
from pathlib import Path

import networkx as nx


def _write_json(data: dict | list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            temporary = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_graph(graph: nx.MultiDiGraph, path: Path, meta: dict) -> None:
    data = nx.node_link_data(graph, edges="links")
    data["metadata"] = meta
    _write_json(data, path)


def load_graph(path: Path) -> tuple[nx.MultiDiGraph, dict | None]:
    if not path.exists():
        return nx.MultiDiGraph(), None
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        raise ValueError("图谱快照中的 metadata 必须是对象")
    return nx.node_link_graph(data, directed=True, multigraph=True, edges="links"), meta


def save_meta(meta: dict, path: Path) -> None:
    _write_json(meta, path)


def load_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def export_graphml(graph: nx.MultiDiGraph) -> str:
    simple = nx.MultiDiGraph(graph)
    for attributes in chain((simple.graph,), (d for _, d in simple.nodes(data=True)),
                            (d for *_, d in simple.edges(data=True))):
        for key, value in list(attributes.items()):
            if isinstance(value, (list, dict)):
                attributes[key] = json.dumps(value, ensure_ascii=False)
    return "\n".join(nx.generate_graphml(simple))
