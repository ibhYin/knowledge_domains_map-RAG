import json
import logging
from copy import deepcopy
from itertools import islice

import networkx as nx

from graphrag.config import settings
from graphrag.graph.entity_resolver import EntityResolver
from graphrag.graph.persistence import export_graphml, load_graph, load_meta, save_graph, save_meta
from graphrag.schemas.extraction import ChunkExtraction, Entity, Relation

DEFAULT_META = {
    "alias_map": {},
    "processed_chunks": {},
    "built_at": None,
    "stats": {},
    "graph_version": 0,
}

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, graph: nx.MultiDiGraph | None = None, alias_map: dict[str, str] | None = None):
        self.G = graph if graph is not None else nx.MultiDiGraph()
        self.resolver = EntityResolver(alias_map)
        self.meta = {**deepcopy(DEFAULT_META), "alias_map": dict(alias_map or {})}
        self._extractions: dict[str, ChunkExtraction] = {}

    # ---------- 持久化 ----------

    def load(self) -> None:
        self.G, meta = load_graph(settings.graph_file)
        if meta is None:
            meta = load_meta(settings.graph_meta_file)
        self.meta = {**deepcopy(DEFAULT_META), **meta}
        self.resolver = EntityResolver(self.meta.get("alias_map", {}))
        self._extractions = {}
        from graphrag.pipeline.chunk_store import ChunkStore
        for cid, digest in self.meta.get("processed_chunks", {}).items():
            ext = ChunkStore().load_extraction(cid, digest, self.meta.get("extraction_fingerprint", ""))
            if ext is not None:
                self._extractions[cid] = ext

    def save(self) -> None:
        meta = {**self.meta, "alias_map": self.resolver.to_dict(),
                "graph_version": self.meta.get("graph_version", 0) + 1}
        meta["stats"] = {**self.stats(), "graph_version": meta["graph_version"]}
        # 图和成功处理记录同一快照原子提交，meta.json 仅兼容旧工具。
        save_graph(self.G, settings.graph_file, meta)
        self.meta = meta
        try:
            save_meta(self.meta, settings.graph_meta_file)
        except OSError as exc:
            logger.warning("图谱快照已保存，meta.json 镜像更新失败: %s", type(exc).__name__)

    def clear(self) -> None:
        self.G = nx.MultiDiGraph()
        self.resolver = EntityResolver()
        self.meta = deepcopy(DEFAULT_META)
        self._extractions = {}

    # ---------- 构建 ----------

    def add_extraction(self, ext: ChunkExtraction, chunk_id: str) -> tuple[int, int]:
        self.rebuild({**self._extractions, chunk_id: ext})
        return len(ext.entities), sum(chunk_id in d["source_chunks"] for *_, d in self.G.edges(data=True))

    def rebuild(self, extractions: dict[str, ChunkExtraction]) -> None:
        self._extractions = dict(extractions)
        self.G = nx.MultiDiGraph()
        self.resolver = EntityResolver()
        self.resolver.prepare(e for ext in extractions.values() for e in ext.entities)
        for cid, ext in sorted(extractions.items()):
            endpoints: dict[str, set[str]] = {}
            for ent in ext.entities:
                key = self._merge_entity(ent, cid)
                for name in [ent.name, *ent.aliases]:
                    endpoints.setdefault(normalize_str(name), set()).add(key)
            for rel in ext.relations:
                sources, targets = endpoints.get(normalize_str(rel.source), set()), endpoints.get(normalize_str(rel.target), set())
                if len(sources) == len(targets) == 1:
                    self._merge_relation(rel, cid, next(iter(sources)), next(iter(targets)))

    def upsert_entity(self, ent: Entity, chunk_id: str) -> str:
        ext = self._extractions.get(chunk_id, ChunkExtraction()).model_copy(deep=True)
        ext.entities.append(ent)
        self.add_extraction(ext, chunk_id)
        return self.resolver.entity_key(ent.name, ent.type.value)

    def _merge_entity(self, ent: Entity, chunk_id: str) -> str:
        key = self.resolver.entity_key(ent.name, ent.type.value)
        if key in self.G:
            n = self.G.nodes[key]
            if normalize_str(n["name"]) != json.loads(key)[1] and normalize_str(ent.name) == json.loads(key)[1]:
                n["name"] = ent.name
            if chunk_id not in n["source_chunks"]:
                n["source_chunks"].append(chunk_id)
                n["mention_count"] += 1
            if len(ent.description) > len(n.get("description", "")):
                n["description"] = ent.description
            for alias in [ent.name, *ent.aliases]:
                if alias not in n["aliases"]:
                    n["aliases"].append(alias)
        else:
            self.G.add_node(
                key,
                name=ent.name,
                type=ent.type.value,
                description=ent.description,
                aliases=list(ent.aliases),
                mention_count=1,
                source_chunks=[chunk_id],
            )
        return key

    def _merge_relation(self, rel: Relation, chunk_id: str, s: str, t: str) -> bool:
        if s == t:
            return False
        key = rel.relation.value
        if self.G.has_edge(s, t, key=key):
            e = self.G[s][t][key]
            if chunk_id not in e["source_chunks"]:
                e["source_chunks"].append(chunk_id)
                e["weight"] += 1
        else:
            self.G.add_edge(
                s,
                t,
                key=key,
                relation=key,
                description=rel.description,
                weight=1,
                source_chunks=[chunk_id],
            )
        return True

    # ---------- 统计与导出 ----------

    def stats(self) -> dict:
        node_types: dict[str, int] = {}
        for _, data in self.G.nodes(data=True):
            t = data.get("type", "UNKNOWN")
            node_types[t] = node_types.get(t, 0) + 1
        edge_relations: dict[str, int] = {}
        for _, _, key, _ in self.G.edges(keys=True, data=True):
            edge_relations[key] = edge_relations.get(key, 0) + 1
        return {
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
            "node_types": node_types,
            "edge_relations": edge_relations,
            "built_at": self.meta.get("built_at"),
            "graph_version": self.meta.get("graph_version", 0),
        }

    def to_viz_data(self, limit: int = 300) -> dict:
        selected = list(islice(self.G.nodes(data=True), limit))
        node_ids = {n for n, _ in selected}
        nodes = [
            {
                "id": n,
                "name": data.get("name", n),
                "type": data.get("type", "UNKNOWN"),
                "description": data.get("description", ""),
                "mention_count": data.get("mention_count", 0),
            }
            for n, data in selected
        ]
        edges = (edge for edge in self.G.edges([n for n, _ in selected], keys=True, data=True)
                 if edge[1] in node_ids)
        links = [
            {
                "id": json.dumps([u, v, key], ensure_ascii=False, separators=(",", ":")),
                "source": u,
                "target": v,
                "relation": key,
                "weight": data.get("weight", 1),
            }
            for u, v, key, data in islice(edges, limit * 3)
        ]
        stats = self.stats()
        return {"nodes": nodes, "links": links, "stats": stats,
                "graph_version": stats["graph_version"],
                "truncated": stats["nodes"] > len(nodes) or stats["edges"] > len(links)}

    def subgraph_viz(self, subgraph: nx.MultiDiGraph, edges: list) -> dict:
        edge_set = {(u, v, k) for u, v, k, _ in edges}
        nodes = [
            {
                "id": n,
                "name": data.get("name", n),
                "type": data.get("type", "UNKNOWN"),
                "description": data.get("description", ""),
                "mention_count": data.get("mention_count", 0),
            }
            for n, data in subgraph.nodes(data=True)
        ]
        links = [
            {
                "source": u,
                "target": v,
                "relation": k,
                "weight": data.get("weight", 1),
            }
            for u, v, k, data in subgraph.edges(keys=True, data=True)
            if (u, v, k) in edge_set
        ]
        return {"nodes": nodes, "links": links}

    # ---------- 检索 ----------

    def locate(self, name: str) -> str | None:
        if name in self.G:
            return name
        key = self.resolver.canonical_key(name)
        if key in self.G:
            return key
        norm = key
        cands = []
        for n, data in self.G.nodes(data=True):
            node_name = data.get("name", n)
            aliases = data.get("aliases", [])
            if norm in normalize_str(node_name) or any(
                norm in normalize_str(a) for a in aliases
            ):
                cands.append(n)
        if len(cands) == 1:
            return cands[0]
        return None

    def expand(self, seeds: list[str], hops: int = 2, max_nodes: int = 40, max_edges: int = 80) -> tuple[nx.MultiDiGraph, list]:
        seeds = list(dict.fromkeys(s for s in seeds if s in self.G))[:max(0, max_nodes)]
        if not seeds:
            return nx.MultiDiGraph(), []
        collected = set(seeds)
        frontier = set(seeds)
        for _ in range(max(1, hops)):
            nxt: set = set()
            for n in frontier:
                nxt |= set(self.G.successors(n)) | set(self.G.predecessors(n))
            new = nxt - collected
            ranked = sorted(
                new,
                key=lambda n: self.G.nodes[n].get("mention_count", 0) + self.G.degree(n),
                reverse=True,
            )
            for n in ranked:
                if len(collected) >= max_nodes:
                    break
                collected.add(n)
            frontier = {n for n in ranked if n in collected}
            if not frontier:
                break
        sub = self.G.subgraph(collected).copy()
        edges = sorted(
            sub.edges(keys=True, data=True),
            key=lambda e: e[3].get("weight", 0),
            reverse=True,
        )
        if max_edges:
            edges = edges[:max_edges]
        return sub, edges

    # ---------- 图谱浏览器 ----------

    def search_entities(self, q: str, limit: int = 20) -> list[dict]:
        q_norm = normalize_str(q)
        if not q_norm:
            return []
        results = []
        for n, data in self.G.nodes(data=True):
            name = data.get("name", n)
            aliases = data.get("aliases", [])
            if q_norm in normalize_str(name) or any(q_norm in normalize_str(a) for a in aliases):
                results.append(
                    {
                        "id": n,
                        "name": name,
                        "type": data.get("type", "UNKNOWN"),
                        "description": data.get("description", ""),
                        "mention_count": data.get("mention_count", 0),
                    }
                )
        results.sort(key=lambda x: x["mention_count"], reverse=True)
        return results[:limit]

    def entity_detail(self, key: str) -> dict | None:
        if key not in self.G:
            return None
        data = self.G.nodes[key]
        neighbors = []
        seen = set()
        for _, v, rkey, edata in self.G.edges(key, keys=True, data=True):
            seen.add(("out", v, rkey))
            neighbors.append(self._neighbor_entry("out", v, rkey, edata))
        for u, _, rkey, edata in self.G.in_edges(key, keys=True, data=True):
            if ("out", u, rkey) not in seen:
                neighbors.append(self._neighbor_entry("in", u, rkey, edata))
        neighbors.sort(key=lambda x: x.get("weight", 0), reverse=True)
        return {
            "id": key,
            "name": data.get("name", key),
            "type": data.get("type", "UNKNOWN"),
            "description": data.get("description", ""),
            "aliases": data.get("aliases", []),
            "mention_count": data.get("mention_count", 0),
            "source_docs": sorted({d.split(":", 1)[0] for d in data.get("source_chunks", [])}),
            "neighbors": neighbors,
        }

    @staticmethod
    def _neighbor_entry(direction: str, node: str, rkey: str, edata: dict) -> dict:
        return {
            "node": node,
            "relation": rkey,
            "direction": direction,
            "weight": edata.get("weight", 1),
            "description": edata.get("description", ""),
        }

    def find_path(self, from_key: str, to_key: str) -> dict | None:
        if from_key not in self.G or to_key not in self.G:
            return None
        try:
            nodes = nx.shortest_path(self.G, source=from_key, target=to_key)
        except nx.NetworkXNoPath:
            return None
        links = []
        for u, v in zip(nodes, nodes[1:]):
            edge_data = self.G.get_edge_data(u, v)
            if not edge_data:
                edge_data = self.G.get_edge_data(v, u)
            if not edge_data:
                continue
            best_key = max(edge_data, key=lambda k: edge_data[k].get("weight", 0))
            links.append({"source": u, "target": v, "relation": best_key})
        return {"nodes": nodes, "links": links}

    def export_graphml(self) -> str:
        return export_graphml(self.G)


def normalize_str(s: str) -> str:
    from graphrag.graph.entity_resolver import normalize

    return normalize(s)
