import logging

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
}

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, graph: nx.MultiDiGraph | None = None, alias_map: dict[str, str] | None = None):
        self.G = graph if graph is not None else nx.MultiDiGraph()
        self.resolver = EntityResolver(alias_map)
        self.meta = {**DEFAULT_META, "alias_map": dict(alias_map or {})}

    # ---------- 持久化 ----------

    def load(self) -> None:
        self.G, meta = load_graph(settings.graph_file)
        if meta is None:
            meta = load_meta(settings.graph_meta_file)
        self.meta = {**DEFAULT_META, **meta}
        self.resolver = EntityResolver(self.meta.get("alias_map", {}))

    def save(self) -> None:
        self.meta["alias_map"] = self.resolver.to_dict()
        self.meta["stats"] = self.stats()
        # 图和成功处理记录同一快照原子提交，meta.json 仅兼容旧工具。
        save_graph(self.G, settings.graph_file, self.meta)
        try:
            save_meta(self.meta, settings.graph_meta_file)
        except OSError as exc:
            logger.warning("图谱快照已保存，meta.json 镜像更新失败: %s", type(exc).__name__)

    def clear(self) -> None:
        self.G = nx.MultiDiGraph()
        self.resolver = EntityResolver()
        self.meta = {**DEFAULT_META}

    # ---------- 构建 ----------

    def add_extraction(self, ext: ChunkExtraction, chunk_id: str) -> tuple[int, int]:
        entity_keys = {self.upsert_entity(e, chunk_id) for e in ext.entities}
        valid_relations = [
            r
            for r in ext.relations
            if self.resolver.canonical_key(r.source) in entity_keys
            and self.resolver.canonical_key(r.target) in entity_keys
        ]
        for rel in valid_relations:
            self.upsert_relation(rel, chunk_id)
        return len(ext.entities), len(valid_relations)

    def upsert_entity(self, ent: Entity, chunk_id: str) -> str:
        key = self.resolver.register_aliases(ent.name, ent.aliases)
        if key in self.G:
            n = self.G.nodes[key]
            n["mention_count"] += 1
            if chunk_id not in n["source_chunks"]:
                n["source_chunks"].append(chunk_id)
            if len(ent.description) > len(n.get("description", "")):
                n["description"] = ent.description
            for alias in ent.aliases:
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

    def upsert_relation(self, rel: Relation, chunk_id: str) -> bool:
        s = self.resolver.canonical_key(rel.source)
        t = self.resolver.canonical_key(rel.target)
        if s not in self.G or t not in self.G:
            return False
        key = rel.relation.value
        if self.G.has_edge(s, t, key=key):
            e = self.G[s][t][key]
            e["weight"] += 1
            if chunk_id not in e["source_chunks"]:
                e["source_chunks"].append(chunk_id)
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
        }

    def to_viz_data(self) -> dict:
        nodes = [
            {
                "id": n,
                "name": data.get("name", n),
                "type": data.get("type", "UNKNOWN"),
                "description": data.get("description", ""),
                "mention_count": data.get("mention_count", 0),
            }
            for n, data in self.G.nodes(data=True)
        ]
        links = [
            {
                "source": u,
                "target": v,
                "relation": key,
                "weight": data.get("weight", 1),
            }
            for u, v, key, data in self.G.edges(keys=True, data=True)
        ]
        return {"nodes": nodes, "links": links}

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
        if cands:
            return max(cands, key=lambda n: self.G.nodes[n].get("mention_count", 0))
        return None

    def expand(self, seeds: list[str], hops: int = 2, max_nodes: int = 40, max_edges: int = 80) -> tuple[nx.MultiDiGraph, list]:
        seeds = [s for s in seeds if s in self.G]
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
