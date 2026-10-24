"""真实模型抽取冒烟检查：会调用两次已配置的模型，仅使用内置样例和临时数据。

运行：python docs/smoke_extract.py
"""

import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    with tempfile.TemporaryDirectory(prefix="graphrag-live-smoke-") as sandbox:
        os.environ["DATA_DIR"] = sandbox

        from graphrag.config import fresh_llm_config
        from graphrag.graph.store import GraphStore
        from graphrag.llm.extractor import QueryEntityExtractor
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
        print(json.dumps({
            "status": "passed",
            "model": fresh_llm_config()["openai_model"],
            "chunks": result["processed"],
            "nodes": result["nodes"],
            "edges": result["edges"],
            "query_entities": [e.name for e in entities],
            "persistence_round_trip": True,
            "temporary_data_only": True,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
