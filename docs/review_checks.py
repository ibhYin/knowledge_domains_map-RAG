"""Offline review regressions; failures describe defects in the reviewed revision.

Run from the repository root: python docs/review_checks.py
Uses existing project dependencies, fake model responses, and temporary data only.
"""

import atexit
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_sandbox = tempfile.TemporaryDirectory(prefix="graphrag-review-")
atexit.register(_sandbox.cleanup)
os.environ.update(
    DATA_DIR=_sandbox.name,
    OPENAI_API_KEY="offline-review-dummy",
    OPENAI_BASE_URL="http://127.0.0.1:9/v1",
)
sys.dont_write_bytecode = True

import networkx as nx
import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from openai import APIConnectionError

from graphrag.api import routes
from graphrag.api.main import app
from graphrag.config import settings
from graphrag.graph.entity_resolver import normalize
from graphrag.graph.store import GraphStore
from graphrag.llm.client import build_llm
from graphrag.llm.extractor import (
    EXTRACTION_SYSTEM_PROMPT,
    QUERY_EXTRACTION_PROMPT,
    EntityExtractor,
    QueryExtractionError,
    QueryEntityExtractor,
)
from graphrag.pipeline.service import RagService
from graphrag.retrieval.evidence import answer_with_evidence
from graphrag.schemas.extraction import ChunkExtraction, Entity, QueryEntities, QueryEntity, Relation


def entity(name, aliases=None):
    return Entity(name=name, type="ORG", aliases=aliases or [])


def extraction():
    return ChunkExtraction(
        entities=[entity("星辰科技"), entity("清华大学")],
        relations=[Relation(source="星辰科技", target="清华大学", relation="PARTNERS_WITH")],
    )


class ReviewChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=_sandbox.name)
        self.addCleanup(self.tmp.cleanup)
        settings.data_dir = Path(self.tmp.name)

    def test_document_prompt_can_be_formatted(self):
        text = '中文文档：{"name": "星辰科技"}，原文含 {text} 和 {unknown}。'
        expected = extraction()

        def respond(prompt):
            messages = prompt.to_messages()
            self.assertEqual([m.type for m in messages], ["system", "human"])
            self.assertEqual(messages[0].content, EXTRACTION_SYSTEM_PROMPT)
            self.assertEqual(messages[1].content, "文本：\n" + text)
            return {"parsed": expected}

        fake_llm = SimpleNamespace(
            with_structured_output=lambda *a, **k: RunnableLambda(respond)
        )
        self.assertEqual(EntityExtractor(llm=fake_llm).extract(text), expected)

    def test_query_prompt_can_be_formatted(self):
        question = '"星辰科技" 与 {"name": "清华大学"} 有什么关系？{unknown}'
        expected = QueryEntities(entities=[QueryEntity(name="星辰科技", type="ORG")])

        def respond(prompt):
            messages = prompt.to_messages()
            self.assertEqual([m.type for m in messages], ["system", "human"])
            self.assertEqual(messages[0].content, QUERY_EXTRACTION_PROMPT)
            self.assertEqual(messages[1].content, "问题：" + question)
            return {"parsed": expected}

        fake_llm = SimpleNamespace(
            with_structured_output=lambda *a, **k: RunnableLambda(respond)
        )
        self.assertEqual(QueryEntityExtractor(llm=fake_llm).extract(question), expected.entities)

    def test_thinking_override_only_applies_to_extraction(self):
        from graphrag.config import fresh_llm_config

        config = fresh_llm_config()
        for configured in (None, "disabled"):
            config["extraction_thinking"] = configured
            for extraction_call in (False, True):
                with self.subTest(configured=configured, extraction=extraction_call), \
                     patch("graphrag.llm.client.fresh_llm_config", return_value=config), \
                     patch("graphrag.llm.client.ChatOpenAI") as constructor:
                    build_llm(for_extraction=extraction_call)
                    expected = {"thinking": {"type": "disabled"}} if configured and extraction_call else None
                    self.assertEqual(constructor.call_args.kwargs["extra_body"], expected)

    def test_both_extractors_use_extraction_client(self):
        for cls, schema in ((EntityExtractor, ChunkExtraction), (QueryEntityExtractor, QueryEntities)):
            with self.subTest(extractor=cls.__name__):
                fake_llm = SimpleNamespace(
                    with_structured_output=lambda *a, **k: RunnableLambda(lambda _: {"parsed": schema()})
                )
                with patch("graphrag.llm.extractor.build_llm", return_value=fake_llm) as factory:
                    cls().extract("测试输入")
                factory.assert_called_once_with(for_extraction=True)

    def test_raw_message_recovery(self):
        for cls in (EntityExtractor, QueryEntityExtractor):
            for content in (
                '{"entities": [], "relations": []}',
                '```json\n{"entities": [{"name": "星辰科技", "type": "ORG"}]}\n```',
            ):
                with self.subTest(extractor=cls.__name__, content=content):
                    extractor = cls()
                    extractor._chain = Mock(
                        invoke=Mock(return_value={"parsed": None, "raw": AIMessage(content=content)})
                    )
                    result = extractor.extract("示例文本")
                    entities = result.entities if isinstance(result, ChunkExtraction) else result
                    self.assertEqual([e.name for e in entities], ["星辰科技"] if "星辰科技" in content else [])

    def test_invalid_extraction_output_is_not_empty_success(self):
        outputs = [{}, {"raw": None}, {"parsed": {"entities": "invalid"}}]
        outputs += [{"raw": AIMessage(content=content)} for content in (
            "not json", "", "[]", '{"entities": [{"name": "错误类型", "type": "INVALID"}]}',
            [{"type": "text", "text": '{"entities": []}'}],
        )]
        for output in outputs:
            with self.subTest(output=output):
                document = EntityExtractor()
                query = QueryEntityExtractor()
                for extractor in (document, query):
                    extractor._chain = Mock(invoke=Mock(return_value=output))
                self.assertIsNone(document.extract("文本"))
                with self.assertRaises(QueryExtractionError) as raised:
                    query.extract("问题")
                self.assertIsNotNone(raised.exception.__cause__)

    def test_model_call_failure_is_safe_and_distinct(self):
        error = APIConnectionError(request=httpx.Request("POST", "http://example.invalid"),
                                   message="sensitive-provider-detail")
        document, query = EntityExtractor(), QueryEntityExtractor()
        for extractor in (document, query):
            extractor._chain = Mock(invoke=Mock(side_effect=error))
        with self.assertLogs("graphrag.llm.extractor", level="WARNING") as logs:
            self.assertIsNone(document.extract("文本"))
            with self.assertRaises(QueryExtractionError) as raised:
                query.extract("问题")
        self.assertIs(raised.exception.__cause__, error)
        self.assertNotIn("sensitive-provider-detail", str(raised.exception))
        self.assertNotIn("sensitive-provider-detail", "\n".join(logs.output))

    def test_programming_errors_are_not_silenced(self):
        for cls in (EntityExtractor, QueryEntityExtractor):
            with self.subTest(extractor=cls.__name__):
                extractor = cls()
                with patch.object(extractor, "_get_chain", side_effect=ValueError("bad template")):
                    with self.assertRaisesRegex(ValueError, "bad template"):
                        extractor.extract("输入")
                extractor._chain = Mock(invoke=Mock(side_effect=RuntimeError("unexpected bug")))
                with self.assertRaisesRegex(RuntimeError, "unexpected bug"):
                    extractor.extract("输入")

    def test_query_api_distinguishes_failure_from_empty_entities(self):
        service = RagService()
        service.search.query_extractor = QueryEntityExtractor()
        for output, expected_status in (
            ({"raw": AIMessage(content="invalid json")}, 502),
            ({"parsed": QueryEntities()}, 200),
        ):
            with self.subTest(status=expected_status):
                service.search.query_extractor._chain = Mock(invoke=Mock(return_value=output))
                with patch.object(routes, "service", service), \
                     patch.object(routes, "_load_history", return_value=[]), \
                     patch.object(routes, "_save_history") as save:
                    response = TestClient(app).post("/api/query", json={"question": "测试问题"})
                self.assertEqual(response.status_code, expected_status)
                if expected_status == 502:
                    self.assertIn("格式错误", response.json()["detail"])
                    save.assert_not_called()
                else:
                    self.assertEqual(response.json()["matched_entities"], [])
                    save.assert_called_once()
        with patch.object(routes, "service", service), \
             patch.object(service.search, "search", side_effect=RuntimeError("unexpected bug")), \
             patch.object(routes, "_save_history") as save:
            response = TestClient(app, raise_server_exceptions=False).post(
                "/api/query", json={"question": "测试问题"}
            )
        self.assertEqual(response.status_code, 500)
        save.assert_not_called()

    def test_graphml_round_trip_with_real_node_attributes(self):
        store = GraphStore()
        store.add_extraction(extraction(), "doc:0")
        restored = nx.parse_graphml(store.export_graphml())
        self.assertEqual(restored.number_of_nodes(), 2)
        self.assertEqual(restored.number_of_edges(), 1)
        key = store.locate("星辰科技")
        self.assertEqual(json.loads(restored.nodes[key]["source_chunks"]), ["doc:0"])
        self.assertEqual(store.G.nodes[key]["source_chunks"], ["doc:0"])
        self.assertEqual(json.loads(next(iter(restored.edges(data=True)))[2]["source_chunks"]), ["doc:0"])

    def test_alias_resolution_is_independent_of_insertion_order(self):
        counts = []
        for entities in (
            [entity("北大"), entity("北京大学", ["北大"])],
            [entity("北京大学", ["北大"]), entity("北大")],
        ):
            store = GraphStore()
            for i, ent in enumerate(entities):
                store.upsert_entity(ent, f"doc:{i}")
            counts.append(store.G.number_of_nodes())
        self.assertEqual(counts, [1, 1])

    def test_processed_chunks_are_not_shared_between_stores(self):
        a, b = GraphStore(), GraphStore()
        for initialize in (lambda s: None, lambda s: s.clear(), lambda s: s.load()):
            initialize(a)
            initialize(b)
            for field in ("processed_chunks", "alias_map", "stats"):
                self.assertIsNot(a.meta[field], b.meta[field])
            a.meta["processed_chunks"]["doc:0"] = "digest"
            self.assertEqual(b.meta["processed_chunks"], {})

    def test_delete_api_removes_facts_without_other_sources(self):
        service = RagService()
        doc = service.ingest([("sample.txt", "星辰科技与清华大学合作。".encode())])[0]
        service.store.add_extraction(extraction(), f"{doc['doc_id']}:0")
        with patch.object(routes, "service", service):
            response = TestClient(app).delete(f"/api/documents/{doc['doc_id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.chunks.list_documents(), [])
        self.assertEqual(service.store.G.number_of_nodes(), 0)

    def test_sources_include_node_only_evidence(self):
        service = RagService()
        doc = service.ingest([("sample.txt", "清华大学是一所大学。".encode())])[0]
        with patch.object(EntityExtractor, "extract", return_value=ChunkExtraction(entities=[entity("清华大学")])):
            service.build_graph()
        fake_llm = SimpleNamespace(invoke=Mock(side_effect=[AIMessage(content=json.dumps({"sentences": [
            {"text": "清华大学是一所大学。", "citations": [{"source_id": 1, "quote": "清华大学是一所大学。"}]}]})),
            AIMessage(content='{"supported":[0]}')]))
        with patch("graphrag.pipeline.service.build_llm", return_value=fake_llm):
            answer = service.answer("清华大学是什么？", seed_override=["清华大学"])
        self.assertEqual(answer["used_docs"], [doc["doc_id"]])
        self.assertEqual(answer["sources"][0]["filename"], "sample.txt")
        self.assertEqual(answer["verification"], "verified")

    def test_evidence_rejects_fabricated_quotes_ids_and_unsupported_claims(self):
        sources = [{"id": 1, "doc_id": "doc", "content": "甲公司没有与乙公司合作。"},
                   {"id": 2, "doc_id": "other", "content": "其他原文"}]
        draft = {"sentences": [
            {"text": "虚构引用。", "citations": [{"source_id": 99, "quote": "其他原文"}]},
            {"text": "虚构片段。", "citations": [{"source_id": 1, "quote": "不存在的原文"}]},
            {"text": "甲公司与乙公司合作。", "citations": [{"source_id": 1, "quote": "与乙公司合作"}]},
            {"text": "甲公司没有与乙公司合作。", "citations": [{"source_id": 1, "quote": "甲公司没有与乙公司合作。"}]},
        ]}
        fake = SimpleNamespace(invoke=Mock(side_effect=[AIMessage(content=json.dumps(draft)),
                                                       AIMessage(content='{"supported":[1]}')]))
        result = answer_with_evidence(fake, "是否合作？", "", sources)
        self.assertEqual(len(result["sentences"]), 1)
        self.assertEqual(result["sentences"][0]["text"], "甲公司没有与乙公司合作。")
        self.assertEqual(result["used_docs"], ["doc"])
        self.assertEqual([s["id"] for s in result["retrieved_sources"]], [2])
        self.assertEqual(result["verification"], "partial")
        verification_input = json.loads(fake.invoke.call_args_list[1].args[0][1].content)
        self.assertEqual(verification_input["sources"][0]["content"], sources[0]["content"])

    def test_evidence_handles_multiple_citations_empty_and_verifier_failure(self):
        sources = [{"id": i, "doc_id": str(i), "content": quote}
                   for i, quote in [(1, "甲在北京。"), (2, "乙在上海。")]]
        draft = {"sentences": [{"text": "甲在北京。乙在上海。", "citations": [
            {"source_id": s["id"], "quote": s["content"]} for s in sources]}]}
        fake = SimpleNamespace(invoke=Mock(side_effect=[AIMessage(content=json.dumps(draft)),
                                                       AIMessage(content='{"supported":[0,1]}')]))
        result = answer_with_evidence(fake, "分别在哪？", "", sources)
        self.assertEqual(len(result["sentences"]), 2)
        self.assertEqual(result["used_docs"], ["1", "2"])
        self.assertIn("[1][2]", result["answer"])
        fake = SimpleNamespace(invoke=Mock(return_value=AIMessage(content='{"sentences":[]}')))
        self.assertEqual(answer_with_evidence(fake, "问题", "", sources)["verification"], "insufficient")
        fake.invoke.assert_called_once()
        fake = SimpleNamespace(invoke=Mock(side_effect=[AIMessage(content=json.dumps(draft)), AIMessage(content="bad json")]))
        with self.assertRaises(QueryExtractionError):
            answer_with_evidence(fake, "问题", "", sources)

    def test_history_keeps_evidence_snapshot_after_document_deletion(self):
        service = RagService()
        doc = service.ingest([("sample.txt", "清华大学是一所大学。".encode())])[0]
        with patch.object(EntityExtractor, "extract", return_value=ChunkExtraction(entities=[entity("清华大学")])):
            service.build_graph()
        fake = SimpleNamespace(invoke=Mock(side_effect=[AIMessage(content=json.dumps({"sentences": [
            {"text": "清华大学是一所大学。", "citations": [{"source_id": 1, "quote": "清华大学是一所大学。"}]}]})),
            AIMessage(content='{"supported":[0]}')]))
        with patch.object(routes, "service", service), \
             patch.object(routes, "_HISTORY_FILE", settings.data_dir / "history.json"), \
             patch("graphrag.pipeline.service.build_llm", return_value=fake):
            client = TestClient(app)
            response = client.post("/api/query", json={"question": "大学？", "seed_override": ["清华大学"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.delete(f"/api/documents/{doc['doc_id']}").status_code, 200)
            saved = client.get("/api/history").json()["history"][0]
        self.assertTrue(saved["sources"][0]["deleted"])
        self.assertEqual(saved["sources"][0]["content"], "清华大学是一所大学。")
        self.assertEqual(saved["sentences"], response.json()["sentences"])

    def test_delete_replays_remaining_sources_without_model(self):
        service = RagService()
        docs = service.ingest([("a.txt", b"A"), ("b.txt", b"B")])
        def extract(text):
            ext = extraction()
            ext.entities[0].description = "A 独有的较长描述" if text == "A" else "B 描述"
            if text == "A":
                ext.entities.append(entity("仅 A 存在"))
            return ext
        with patch.object(EntityExtractor, "extract", side_effect=extract):
            service.build_graph()
        with patch.object(EntityExtractor, "extract") as model:
            self.assertTrue(service.delete_document(docs[0]["doc_id"]))
        model.assert_not_called()
        self.assertNotIn("仅a存在", service.store.G)
        company, university = service.store.locate("星辰科技"), service.store.locate("清华大学")
        node = service.store.G.nodes[company]
        self.assertEqual(node["description"], "B 描述")
        self.assertEqual(node["mention_count"], 1)
        self.assertEqual(node["source_chunks"], [f"{docs[1]['doc_id']}:0"])
        self.assertEqual(service.store.G[company][university]["PARTNERS_WITH"]["weight"], 1)
        restored = RagService()
        restored.load()
        self.assertEqual(restored.store.G.number_of_nodes(), 2)
        self.assertEqual(len(restored.list_documents()), 1)

    def test_delete_failure_preserves_data_and_committed_delete_recovers(self):
        service = RagService()
        doc = service.ingest([("sample.txt", b"A")])[0]["doc_id"]
        with patch.object(EntityExtractor, "extract", return_value=extraction()):
            service.build_graph()
        with patch.object(GraphStore, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                service.delete_document(doc)
        self.assertEqual(len(service.list_documents()), 1)
        self.assertEqual(service.store.G.number_of_nodes(), 2)
        with patch.object(service.chunks, "delete_document", side_effect=OSError("cleanup interrupted")):
            self.assertTrue(service.delete_document(doc))
        self.assertEqual(service.list_documents(), [])
        self.assertEqual(service.store.G.number_of_nodes(), 0)
        with patch.object(EntityExtractor, "extract") as model:
            service.build_graph()
        model.assert_not_called()
        restored = RagService()
        restored.load()
        self.assertEqual(restored.chunks.iter_chunks(), [])
        self.assertFalse(restored.chunks._extraction_file(f"{doc}:0").exists())

    def test_delete_refuses_to_lose_uncached_remaining_facts(self):
        service = RagService()
        docs = service.ingest([("a.txt", b"A"), ("b.txt", b"B")])
        with patch.object(EntityExtractor, "extract", return_value=extraction()):
            service.build_graph()
        service.chunks._extraction_file(f"{docs[1]['doc_id']}:0").unlink()
        with self.assertRaisesRegex(ValueError, "缓存"):
            service.delete_document(docs[0]["doc_id"])
        self.assertEqual(len(service.list_documents()), 2)

    def test_seed_count_respects_node_limit(self):
        store = GraphStore()
        seeds = [store.upsert_entity(entity(name), "doc:0") for name in ("甲", "乙")]
        subgraph, _ = store.expand(seeds, max_nodes=1)
        self.assertLessEqual(subgraph.number_of_nodes(), 1)

    def test_failed_extraction_is_not_reported_as_success(self):
        service = RagService()
        service.ingest([("sample.txt", "星辰科技与清华大学合作。".encode())])
        service.store.add_extraction(extraction(), "old:0")
        service.store.meta["built_at"] = "previous build"
        progress = []
        with patch.object(EntityExtractor, "extract", return_value=None), \
             patch.object(GraphStore, "save") as save:
            result = service.build_graph(progress=progress.append)
        self.assertEqual(result["status"], "error")
        self.assertEqual((result["processed"], result["total"], result["failed"]), (1, 1, 1))
        self.assertEqual(progress[-1], result)
        self.assertTrue(result["error"])
        self.assertEqual(service.store.meta["built_at"], "previous build")
        self.assertEqual(service.store.G.number_of_nodes(), 2)
        save.assert_not_called()

    def test_partial_build_retries_only_failed_chunks(self):
        service = RagService()
        service.ingest([("good.txt", "成功片段".encode()), ("bad.txt", "失败片段".encode())])
        progress = []
        with patch.object(EntityExtractor, "extract", side_effect=lambda text: extraction() if text == "成功片段" else None):
            result = service.build_graph(progress=progress.append)
        self.assertEqual(result["status"], "partial")
        self.assertEqual((result["processed"], result["total"], result["failed"]), (2, 2, 1))
        self.assertEqual(progress[-1], result)
        self.assertEqual(len(service.store.meta["processed_chunks"]), 1)
        restored = GraphStore()
        restored.load()
        self.assertEqual(restored.meta["processed_chunks"], service.store.meta["processed_chunks"])
        with patch.object(EntityExtractor, "extract", return_value=extraction()) as extract:
            retried = service.build_graph()
        extract.assert_called_once_with("失败片段")
        self.assertEqual(retried["status"], "done")
        self.assertEqual((retried["processed"], retried["failed"]), (1, 0))
        self.assertIs(service.search.store, service.store)
        self.assertEqual(len(service.store.meta["processed_chunks"]), 2)

    def test_empty_build_preserves_existing_build_time(self):
        service = RagService()
        service.store.meta["built_at"] = "previous build"
        progress = []
        with patch.object(EntityExtractor, "extract") as extract, \
             patch.object(GraphStore, "save") as save:
            result = service.build_graph(progress=progress.append)
        self.assertEqual(result["status"], "done")
        self.assertEqual((result["processed"], result["total"], result["failed"]), (0, 0, 0))
        self.assertIn("没有可构建", result["message"])
        self.assertEqual(service.store.meta["built_at"], "previous build")
        self.assertEqual(progress[-1], result)
        extract.assert_not_called()
        save.assert_not_called()

    def test_empty_extraction_is_success_and_not_retried(self):
        service = RagService()
        service.ingest([("sample.txt", "没有独立实体的普通文字".encode())])
        with patch.object(EntityExtractor, "extract", return_value=ChunkExtraction()) as extract:
            first = service.build_graph()
            second = service.build_graph()
        self.assertEqual((first["status"], first["processed"], first["failed"]), ("done", 1, 0))
        self.assertEqual((second["status"], second["processed"]), ("done", 0))
        self.assertIn("无需重复", second["message"])
        extract.assert_called_once()

    def test_failed_save_does_not_publish_or_skip_chunks(self):
        service = RagService()
        service.ingest([("sample.txt", "星辰科技与清华大学合作。".encode())])
        service.store.meta["built_at"] = "previous build"
        progress = []
        with patch.object(EntityExtractor, "extract", return_value=extraction()), \
             patch.object(GraphStore, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                service.build_graph(progress=progress.append)
        self.assertEqual(service.store.G.number_of_nodes(), 0)
        self.assertEqual(service.store.meta["processed_chunks"], {})
        self.assertEqual(service.store.meta["built_at"], "previous build")
        self.assertTrue(all(s["status"] == "running" for s in progress))
        with patch.object(EntityExtractor, "extract", return_value=extraction()) as extract:
            result = service.build_graph()
        self.assertEqual(result["status"], "done")
        extract.assert_not_called()  # 已保存抽取缓存，图谱保存失败无需再次调用模型。

    def test_cached_extractions_rebuild_graph_without_model(self):
        service = RagService()
        service.ingest([("sample.txt", "星辰科技与清华大学合作。".encode())])
        with patch.object(EntityExtractor, "extract", return_value=extraction()):
            service.build_graph()
        restored = RagService()
        with patch.object(EntityExtractor, "extract") as extract:
            result = restored.build_graph()
        extract.assert_not_called()
        self.assertEqual(result["nodes"], 2)
        self.assertEqual(result["edges"], 1)

    def test_cache_invalidates_on_config_or_content_changes(self):
        from graphrag.config import fresh_llm_config

        service = RagService()
        record = {"content": "原文", "chunk_index": 0, "metadata": {"doc_id": "doc"}}
        with patch.object(service.chunks, "iter_chunks", return_value=[record]), \
             patch.object(EntityExtractor, "extract", return_value=extraction()) as extract:
            service.build_graph()
            service.build_graph()
            self.assertEqual(extract.call_count, 1)
            record["content"] = "修改后的原文"
            service.build_graph()
            self.assertEqual(extract.call_count, 2)
            config = {**fresh_llm_config(), "openai_model": "different-model"}
            with patch("graphrag.pipeline.service.fresh_llm_config", return_value=config):
                service.build_graph()
            self.assertEqual(extract.call_count, 3)
        self.assertEqual(service.store.G.nodes[service.store.locate("星辰科技")]["mention_count"], 1)

    def test_alias_ambiguity_and_types_stay_separate_in_any_order(self):
        from itertools import permutations

        entities = [entity("北大"), entity("北京大学", ["北大"]), entity("北方大学", ["北大"]),
                    Entity(name="北京大学", type="LOCATION")]
        graphs = []
        for order in permutations(entities):
            store = GraphStore()
            store.rebuild({f"doc:{entities.index(e)}": ChunkExtraction(entities=[e]) for e in order})
            self.assertEqual(store.G.number_of_nodes(), 4)
            self.assertIsNone(store.locate("北京大学"))
            self.assertIsNone(store.locate("北大"))
            self.assertNotEqual(store.resolver.entity_key("北京大学", "ORG"),
                                store.resolver.entity_key("北京大学", "LOCATION"))
            graphs.append(sorted(store.G.nodes))
        self.assertTrue(all(g == graphs[0] for g in graphs))

    def test_alias_merge_preserves_relations_sources_and_repeated_builds(self):
        service = RagService()
        docs = service.ingest([("a.txt", b"A"), ("b.txt", b"B")])
        first = ChunkExtraction(entities=[entity("北大"), entity("合作方")],
            relations=[Relation(source="北大", target="合作方", relation="PARTNERS_WITH")])
        second = ChunkExtraction(entities=[entity("北京大学", ["北大"])])
        with patch.object(EntityExtractor, "extract", side_effect=lambda text: first if text == "A" else second):
            service.build_graph([docs[0]["doc_id"]])
            service.build_graph([docs[1]["doc_id"]])
        self.assertEqual(service.store.G.number_of_nodes(), 2)
        self.assertEqual(service.store.G.number_of_edges(), 1)
        key = service.store.locate("北大")
        self.assertEqual(service.store.G.nodes[key]["name"], "北京大学")
        self.assertEqual(service.store.G.nodes[key]["mention_count"], 2)
        restored = RagService()
        restored.load()
        self.assertEqual(restored.store.locate("北大"), key)

    def test_corrupt_cache_is_replaced_and_empty_success_is_cached(self):
        service = RagService()
        record = {"content": "普通文字", "chunk_index": 0, "metadata": {"doc_id": "doc"}}
        with patch.object(service.chunks, "iter_chunks", return_value=[record]), \
             patch.object(EntityExtractor, "extract", return_value=ChunkExtraction()) as extract:
            service.build_graph()
            service.chunks._extraction_file("doc:0").write_text("{", encoding="utf-8")
            service.build_graph()
            service.build_graph()
        self.assertEqual(extract.call_count, 2)
        self.assertEqual(service.store.G.number_of_nodes(), 0)

    def test_unexpected_build_error_does_not_publish_partial_results(self):
        service = RagService()
        service.ingest([("sample.txt", "星辰科技与清华大学合作。".encode())])
        progress = []
        with patch.object(EntityExtractor, "extract", side_effect=RuntimeError("unexpected bug")), \
             patch.object(GraphStore, "save") as save:
            with self.assertRaisesRegex(RuntimeError, "unexpected bug"):
                service.build_graph(progress=progress.append)
        self.assertEqual(service.store.meta["processed_chunks"], {})
        self.assertTrue(all(s["status"] == "running" for s in progress))
        save.assert_not_called()

    def test_build_api_reports_terminal_states(self):
        save = GraphStore.save
        for outcome, expected_status in (
            ("success", "done"), ("partial", "partial"), ("failed", "error"),
            ("save_error", "error"), ("program_error", "error"),
        ):
            with self.subTest(outcome=outcome):
                service = RagService()
                documents = service.ingest([("good.txt", "成功片段".encode()),
                                            ("bad.txt", "失败片段".encode())])

                def extract(text):
                    if outcome == "program_error":
                        raise RuntimeError("unexpected bug")
                    if outcome == "failed" or (outcome == "partial" and text == "失败片段"):
                        return None
                    return extraction()

                synchronous_threads = SimpleNamespace(
                    Thread=lambda target, daemon: SimpleNamespace(start=target)
                )
                with patch.object(routes, "service", service), \
                     patch.object(routes, "threading", synchronous_threads), \
                     patch.object(routes, "_jobs", {}), \
                     patch.object(EntityExtractor, "extract", side_effect=extract), \
                     patch.object(GraphStore, "save", autospec=True,
                                  side_effect=OSError("disk full") if outcome == "save_error" else save):
                    client = TestClient(app)
                    response = client.post("/api/graph/build", json={"doc_ids": [d["doc_id"] for d in documents]})
                    self.assertEqual(response.status_code, 200)
                    state = client.get(f"/api/graph/build/status/{response.json()['job_id']}").json()
                self.assertEqual(state["status"], expected_status)
                if expected_status == "error":
                    self.assertTrue(state["error"])
                else:
                    self.assertEqual((state["processed"], state["total"]), (2, 2))
                    self.assertEqual(state["failed"], 1 if outcome == "partial" else 0)

    def test_current_build_discovery_and_duplicate_submission(self):
        jobs = {
            "111111111111": {"status": "running", "processed": 7, "total": 20},
            "222222222222": {"status": "done", "processed": 1, "total": 1},
        }
        with patch.object(routes, "_jobs", jobs), \
             patch.object(routes, "threading", SimpleNamespace(Thread=Mock())) as thread_api:
            client = TestClient(app)
            current = client.get("/api/graph/build/current").json()
            self.assertEqual(current["job_id"], "111111111111")
            self.assertEqual(current["processed"], 7)
            response = client.post("/api/graph/build", json={})
            self.assertEqual(response.json()["job_id"], "111111111111")
            thread_api.Thread.assert_not_called()
            jobs["111111111111"]["status"] = "done"
            self.assertEqual(client.get("/api/graph/build/current").json()["job_id"], "222222222222")
            jobs.clear()
            self.assertEqual(client.get("/api/graph/build/current").json(), {"job_id": None})

    def test_build_progress_does_not_wait_for_first_submitted_chunk(self):
        service = RagService()
        release = threading.Event()
        records = [{"content": text, "chunk_index": i, "metadata": {"doc_id": "doc"}}
                   for i, text in enumerate(("slow", "fast"))]

        def extract(text):
            if text == "slow":
                self.assertTrue(release.wait(3), "Progress was blocked by the first submitted request")
            return extraction()

        def progress(state):
            if state["processed"] == 1:
                release.set()

        with patch.object(service.chunks, "iter_chunks", return_value=records), \
             patch.object(EntityExtractor, "extract", side_effect=extract):
            result = service.build_graph(progress=progress)
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["status"], "done")

    def test_checkpoint_survives_later_failure_and_resumes(self):
        service = RagService()
        release = threading.Event()
        records = [{"content": text, "chunk_index": i, "metadata": {"doc_id": "doc"}}
                   for i, text in enumerate(("good", "bad"))]

        def extract(text):
            if text == "bad":
                self.assertTrue(release.wait(3))
                raise RuntimeError("later failure")
            return extraction()

        def progress(state):
            if state["processed"] == 1:
                self.assertEqual(state["checkpoint_processed"], 1)
                self.assertEqual(state["nodes"], 2)
                restored = GraphStore()
                restored.load()
                self.assertEqual(len(restored.meta["processed_chunks"]), 1)
                release.set()

        with patch.object(service.chunks, "iter_chunks", return_value=records), \
             patch.object(settings, "build_checkpoint_interval", 1), \
             patch.object(EntityExtractor, "extract", side_effect=extract):
            with self.assertRaisesRegex(RuntimeError, "later failure"):
                service.build_graph(progress=progress)
        resumed = RagService()
        resumed.store.load()
        with patch.object(resumed.chunks, "iter_chunks", return_value=records), \
             patch.object(EntityExtractor, "extract", return_value=extraction()) as extract:
            result = resumed.build_graph()
        extract.assert_called_once_with("bad")
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(resumed.store.meta["processed_chunks"]), 2)

    def test_first_result_is_published_without_mutating_its_snapshot(self):
        service = RagService()
        release = threading.Event()
        records = [{"content": text, "chunk_index": i, "metadata": {"doc_id": "doc"}}
                   for i, text in enumerate(("first", "second"))]
        published = []

        def extract(text):
            if text == "second":
                self.assertTrue(release.wait(3))
            return ChunkExtraction(entities=[entity(text)])

        def progress(state):
            if state["processed"] == 1:
                self.assertEqual(state["checkpoint_processed"], 1)
                published.append(service.store.G)
                self.assertEqual(published[0].number_of_nodes(), 1)
                release.set()

        with patch.object(service.chunks, "iter_chunks", return_value=records), \
             patch.object(settings, "build_checkpoint_interval", 50), \
             patch.object(EntityExtractor, "extract", side_effect=extract):
            service.build_graph(progress=progress)
        self.assertEqual(published[0].number_of_nodes(), 1)
        self.assertEqual(service.store.G.number_of_nodes(), 2)
        self.assertIsNot(published[0], service.store.G)

    def test_snapshot_is_atomic_and_legacy_graph_can_load(self):
        store = GraphStore()
        store.add_extraction(extraction(), "doc:0")
        store.meta["processed_chunks"] = {"doc:0": "old-hash"}
        store.save()
        original = settings.graph_file.read_bytes()
        store.upsert_entity(entity("新实体"), "doc:1")
        with patch("graphrag.graph.persistence.os.replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                store.save()
        self.assertEqual(settings.graph_file.read_bytes(), original)
        restored = GraphStore()
        restored.load()
        self.assertNotIn("新实体", restored.G)
        self.assertEqual(restored.meta["processed_chunks"], {"doc:0": "old-hash"})
        legacy = json.loads(original)
        legacy.pop("metadata")
        settings.graph_file.write_text(json.dumps(legacy))
        restored.load()
        self.assertEqual(restored.meta["processed_chunks"], {"doc:0": "old-hash"})

    def test_committed_snapshot_does_not_depend_on_meta_mirror(self):
        store = GraphStore()
        store.add_extraction(extraction(), "doc:0")
        store.meta["processed_chunks"] = {"doc:0": "hash"}
        with patch("graphrag.graph.store.save_meta", side_effect=OSError("mirror error")), \
             self.assertLogs("graphrag.graph.store", level="WARNING"):
            store.save()
        restored = GraphStore()
        restored.load()
        self.assertEqual(restored.G.number_of_nodes(), 2)
        self.assertEqual(restored.meta["processed_chunks"], {"doc:0": "hash"})

    def test_buffered_results_publish_while_next_model_call_is_waiting(self):
        service = RagService()
        first_saved, second_saved = threading.Event(), threading.Event()
        states = []
        records = [{"content": text, "chunk_index": i, "metadata": {"doc_id": "doc"}}
                   for i, text in enumerate(("first", "second", "last"))]

        def extract(text):
            if text == "second":
                self.assertTrue(first_saved.wait(3))
            elif text == "last":
                self.assertTrue(second_saved.wait(3), "Buffered results were waiting for another model response")
            return ChunkExtraction(entities=[entity(text)])

        def progress(state):
            states.append(dict(state))
            if state["processed"] == 1 and state.get("checkpoint_processed") == 1:
                first_saved.set()
            if state["processed"] == 2 and state.get("checkpoint_processed") == 2:
                second_saved.set()

        with patch.object(service.chunks, "iter_chunks", return_value=records), \
             patch.object(settings, "build_checkpoint_interval", 100), \
             patch.object(settings, "build_publish_interval", 0.1), \
             patch.object(EntityExtractor, "extract", side_effect=extract):
            result = service.build_graph(progress=progress)
        self.assertEqual(result["status"], "done")
        self.assertTrue(any(s["processed"] == 2 and s.get("checkpoint_processed") == 1 for s in states))
        versions = [s["graph_version"] for s in states]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(result["graph_version"], 3)

    def test_graph_versions_advance_only_on_committed_saves(self):
        store = GraphStore()
        store.add_extraction(extraction(), "doc:0")
        store.save()
        self.assertEqual(store.meta["graph_version"], 1)
        with patch("graphrag.graph.persistence.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.save()
        self.assertEqual(store.meta["graph_version"], 1)
        store.save()
        self.assertEqual(store.meta["graph_version"], 2)
        restored = GraphStore()
        restored.load()
        self.assertEqual(restored.meta["graph_version"], 2)

    def test_preview_has_consistent_version_counts_and_stable_bounded_ids(self):
        service = RagService()
        for name in ("a", "b", "c", "d"):
            service.store.upsert_entity(entity(name), "doc:0")
        for u in service.store.G:
            for v in service.store.G:
                if u != v:
                    for relation in ("USES", "RELATED_TO", "PARTNERS_WITH"):
                        service.store.G.add_edge(u, v, key=relation, weight=1)
        service.store.save()
        with patch.object(routes, "service", service):
            client = TestClient(app)
            preview = client.get("/api/graph/viz?limit=3").json()
            repeated = client.get("/api/graph/viz?limit=3").json()
            self.assertEqual(client.get("/api/graph/viz?limit=0").status_code, 422)
            self.assertEqual(client.get("/api/graph/viz?limit=1001").status_code, 422)
        self.assertEqual(preview["graph_version"], preview["stats"]["graph_version"])
        self.assertEqual((preview["stats"]["nodes"], preview["stats"]["edges"]), (4, 36))
        self.assertEqual((len(preview["nodes"]), len(preview["links"])), (3, 9))
        self.assertTrue(preview["truncated"])
        self.assertEqual(preview, repeated)
        ids = {n["id"] for n in preview["nodes"]}
        self.assertTrue(all(e["source"] in ids and e["target"] in ids for e in preview["links"]))
        self.assertEqual(len({e["id"] for e in preview["links"]}), len(preview["links"]))

    def test_running_build_blocks_clear_and_document_delete(self):
        service = RagService()
        service.store.add_extraction(extraction(), "doc:0")
        with patch.object(routes, "service", service), \
             patch.object(routes, "_jobs", {"test": {"status": "running"}}), \
             patch.object(service.chunks, "delete_document") as delete, \
             patch.object(service.store, "save") as save:
            client = TestClient(app)
            self.assertEqual(client.post("/api/graph/clear", json={}).status_code, 409)
            self.assertEqual(client.delete("/api/documents/example").status_code, 409)
        delete.assert_not_called()
        save.assert_not_called()
        self.assertEqual(service.store.G.number_of_nodes(), 2)

    def test_unchanged_chunks_skip_extraction(self):
        service = RagService()
        service.ingest([("sample.txt", "星辰科技与清华大学合作。".encode())])
        with patch.object(EntityExtractor, "extract", return_value=extraction()) as extract:
            first = service.build_graph()
            calls = extract.call_count
            second = service.build_graph()
        self.assertEqual(first["processed"], 1)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(extract.call_count, calls)

    def test_health_reports_process_identity(self):
        client = TestClient(app)
        body = client.get("/api/health").json()
        self.assertEqual(body["pid"], os.getpid())
        self.assertTrue(body["started_at"])
        self.assertTrue(body["code_mtime"])

    def test_source_watcher_reloads_when_idle(self):
        from graphrag.supervisor import app as supervisor_app

        calls = []

        class _Manager:
            def restart(self, reason=""):
                calls.append(reason)
                return {"ok": True, "message": "restarted"}

        with patch.object(supervisor_app.SourceWatcher, "_scan", return_value={"a.py": 1.0}), \
                patch.object(supervisor_app.SourceWatcher, "_build_running", return_value=False), \
                patch.object(supervisor_app.time, "sleep", return_value=None):
            watcher = supervisor_app.SourceWatcher(_Manager())
            watcher._snapshot = {"a.py": 0.0}
            watcher.poll_once()
        self.assertEqual(len(calls), 1)
        self.assertFalse(watcher.pending)

    def test_source_watcher_defers_reload_while_build_running(self):
        from graphrag.supervisor import app as supervisor_app

        calls = []

        class _Manager:
            def restart(self, reason=""):
                calls.append(reason)
                return {"ok": True, "message": "restarted"}

        with patch.object(supervisor_app.SourceWatcher, "_scan", return_value={"a.py": 1.0}), \
                patch.object(supervisor_app.SourceWatcher, "_build_running", return_value=True), \
                patch.object(supervisor_app.time, "sleep", return_value=None):
            watcher = supervisor_app.SourceWatcher(_Manager())
            watcher._snapshot = {"a.py": 0.0}
            watcher.poll_once()
        self.assertEqual(calls, [])
        self.assertTrue(watcher.pending)

        with patch.object(supervisor_app.SourceWatcher, "_build_running", return_value=False), \
                patch.object(supervisor_app.time, "sleep", return_value=None):
            watcher.poll_once()
        self.assertEqual(len(calls), 1)
        self.assertFalse(watcher.pending)

    def test_unicode_normalization(self):
        self.assertEqual(normalize(" ＡＩ （测试） "), normalize("ai(测试)"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
