"""真实模型全流程检查：正常调用四次已配置模型，仅使用内置样例和临时数据。

运行：python docs/smoke_extract.py
"""

import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    with tempfile.TemporaryDirectory(prefix="graphrag-live-smoke-") as sandbox:
        os.environ["DATA_DIR"] = sandbox

        from graphrag.config import fresh_llm_config
        from graphrag.graph.store import GraphStore
        from graphrag.llm.extractor import EntityExtractor, QueryEntityExtractor
        from graphrag.pipeline.service import RagService

        text = "2024年，星辰科技与清华大学在北京共同建立人工智能联合实验室。"
        service = RagService()
        document = service.ingest([("extraction-smoke.txt", text.encode("utf-8"))])[0]
        assert document["chunk_count"] == 1
        result = service.build_graph()
        assert result["status"] == "done" and result["failed"] == 0, result
        assert result["nodes"] > 0 and result["edges"] > 0, result

        restored = GraphStore()
        restored.load()
        assert restored.G.number_of_nodes() == result["nodes"]
        assert restored.G.number_of_edges() == result["edges"]
        assert len(restored.meta["processed_chunks"]) == 1
        company = restored.locate("星辰科技")
        university = restored.locate("清华大学")
        assert company and university
        assert (restored.G.has_edge(company, university, key="PARTNERS_WITH")
                or restored.G.has_edge(university, company, key="PARTNERS_WITH"))

        entities = QueryEntityExtractor().extract("星辰科技与清华大学有什么关系？")
        located = {restored.locate(e.name) for e in entities}
        assert {company, university} <= located, [e.name for e in entities]
        answer = service.answer("星辰科技与清华大学有什么关系？", seed_override=["星辰科技", "清华大学"])
        assert answer["sentences"] and answer["sources"], answer
        assert answer["verification"] in {"verified", "partial"}, answer
        for sentence in answer["sentences"]:
            for citation in sentence["citations"]:
                source = next(s for s in answer["sources"] if s["id"] == citation["source_id"])
                assert citation["quote"] in source["content"]
        import networkx as nx
        assert nx.parse_graphml(service.store.export_graphml()).number_of_nodes() == result["nodes"]
        service.store.clear()
        service.store.save()
        with patch.object(EntityExtractor, "extract", side_effect=AssertionError("缓存复用不应再次调用模型")):
            rebuilt = service.build_graph()
            assert rebuilt["nodes"] == result["nodes"]
            assert service.delete_document(document["doc_id"])
        restarted = RagService()
        restarted.load()
        assert restarted.store.G.number_of_nodes() == 0 and restarted.list_documents() == []
        print(json.dumps({
            "status": "passed",
            "model": fresh_llm_config()["openai_model"],
            "chunks": result["processed"],
            "nodes": result["nodes"],
            "edges": result["edges"],
            "query_entities": [e.name for e in entities],
            "persistence_round_trip": True,
            "sentence_verification": answer["verification"],
            "cited_sentences": len(answer["sentences"]),
            "cache_rebuild_without_model": True,
            "delete_and_restart": True,
            "graphml_round_trip": True,
            "temporary_data_only": True,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
