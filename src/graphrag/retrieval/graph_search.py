import networkx as nx

from graphrag.graph.store import GraphStore
from graphrag.graph.entity_resolver import normalize
from graphrag.llm.extractor import QueryEntityExtractor


class GraphSearch:
    def __init__(self, store: GraphStore, query_extractor: QueryEntityExtractor | None = None):
        self.store = store
        self.query_extractor = query_extractor

    def search(
        self,
        question: str,
        hops: int = 2,
        max_nodes: int = 40,
        max_edges: int = 80,
        seed_override: list[str] | None = None,
        store: GraphStore | None = None,
    ) -> dict:
        """从问题抽取种子实体 → 定位 → BFS 扩张，返回子图与命中信息。"""
        store = store if store is not None else self.store
        if seed_override:
            seed_names = seed_override
        else:
            if self.query_extractor is None:
                self.query_extractor = QueryEntityExtractor()
            seed_names = [e.name for e in self.query_extractor.extract(question)]

        matched = []
        seeds = []
        for name in seed_names:
            key = store.locate(name)
            if key is not None:
                matched.append(
                    {
                        "query": name,
                        "node": key,
                        "name": store.G.nodes[key].get("name", key),
                    }
                )
                node = store.G.nodes[key]
                score = 2 if name == key or normalize(name) == normalize(node.get("name", key)) else int(
                    any(normalize(name) == normalize(a) for a in node.get("aliases", [])))
                seeds.append((score, key))

        seeds = list(dict.fromkeys(key for _, key in sorted(seeds, key=lambda item: item[0], reverse=True)))[:max_nodes]
        matched = [match for match in matched if match["node"] in seeds]

        subgraph: nx.MultiDiGraph
        edges: list
        if seeds:
            subgraph, edges = store.expand(seeds, hops=hops, max_nodes=max_nodes, max_edges=max_edges)
        else:
            subgraph, edges = nx.MultiDiGraph(), []

        return {
            "matched_entities": matched,
            "seed_nodes": seeds,
            "subgraph": subgraph,
            "edges": edges,
        }
