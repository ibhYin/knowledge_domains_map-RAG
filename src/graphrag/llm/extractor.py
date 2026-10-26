import json
import logging
import re
from typing import Optional

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from openai import APIError
from pydantic import ValidationError

from graphrag.config import fresh_llm_config
from graphrag.llm.client import build_llm
from graphrag.schemas.extraction import ChunkExtraction, QueryEntities

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """你是一名专业的中文知识图谱构建助手。请从给定文本片段中抽取实体与关系。
只抽取文本中明确出现、有独立指称意义的实体，不要联想、不要补充文本外的知识。

【实体类型】
- 人物(PERSON)：真实或虚构的个人，使用最完整、最常用的称呼。
- 组织(ORG)：公司、机构、学校、政府单位、团体。
- 地点(LOCATION)：国家、城市、地区、山川、建筑等地理实体。
- 概念/术语(CONCEPT)：领域内的抽象概念、理论、方法、技术名词。
- 时间/时期(TIME)：具体年份/日期/时间段，务必规范为「2023年」形式，把「今年」「去年」改写为具体年份。
- 事件(EVENT)：有明确时间与参与方的商业/历史/社会事件。

【关系类型（relation 字段仅可用以下值）】
- MEMBER_OF 隶属：成员、员工、下属
- AFFILIATED_WITH 任职：担任职务、管理
- FOUNDED_BY 创建：创立、创办
- CREATED 提出/发布：提出理论、发布产品
- LOCATED_IN 位于
- RELATED_TO 相关/涉及：一般关联、参与、讨论
- CAUSES 导致：因果
- AFFECTS 影响
- PROPOSED_BY 提出者
- INVENTED_BY 发明者
- PARTNERS_WITH 合作
- USES 使用：方法、技术、工具
- IN_PERIOD 时间归属：实体与时期的关系

【抽取规则】
1. 每个实体必须有规范名 name（最常用完整称呼）、类型 type、一句话中文描述 description。
2. 若同一实体在文本中有多种叫法（全称/简称/别称），把其余叫法填入 aliases。
3. 每条关系必须连接本片段实体列表中的两个 name，使用上面的标准 relation 值。
4. 时间表达必须规范化成具体年份，禁止保留「今年」「去年」等相对时间。
5. 若片段没有实体或关系，返回空数组，绝不编造。
6. 同片段内合并重复实体，同义表述只抽取一次。
7. 只输出 JSON，不要输出任何解释性文字。JSON 格式为：
{"entities": [{"name": "...", "type": "...", "description": "...", "aliases": []}],
 "relations": [{"source": "...", "target": "...", "relation": "...", "description": "..."}]}

【示例】
文本：2023年，李华在北京创办了星辰科技公司，专注于人工智能领域，并与清华大学达成合作。
实体：[{"name":"李华","type":"PERSON","description":"星辰科技的创始人","aliases":[]},
      {"name":"星辰科技","type":"ORG","description":"2023年创办的人工智能公司","aliases":["星辰科技公司"]},
      {"name":"北京","type":"LOCATION","description":"星辰科技所在地","aliases":[]},
      {"name":"清华大学","type":"ORG","description":"与星辰科技合作的大学","aliases":[]},
      {"name":"2023年","type":"TIME","description":"星辰科技创办年份","aliases":[]},
      {"name":"人工智能","type":"CONCEPT","description":"星辰科技专注的领域","aliases":[]}]
关系：[{"source":"李华","target":"星辰科技","relation":"FOUNDED_BY","description":"李华于2023年创办星辰科技"},
      {"source":"星辰科技","target":"北京","relation":"LOCATED_IN","description":"星辰科技位于北京"},
      {"source":"星辰科技","target":"清华大学","relation":"PARTNERS_WITH","description":"星辰科技与清华大学合作"},
      {"source":"星辰科技","target":"人工智能","relation":"RELATED_TO","description":"星辰科技专注人工智能"},
      {"source":"星辰科技","target":"2023年","relation":"IN_PERIOD","description":"星辰科技创办于2023年"}]"""

QUERY_EXTRACTION_PROMPT = """你是实体识别助手。从用户问题中抽取明确提到的实体，只抽取问题中明确出现的实体名称，不要联想。

【实体类型】
- PERSON 人物 / ORG 组织 / LOCATION 地点 / CONCEPT 概念 / TIME 时间 / EVENT 事件

只输出 JSON，格式：{"entities": [{"name": "...", "type": "..."}]}，没有则返回空数组。
若实体类型不确定，type 填 null。"""


class QueryExtractionError(RuntimeError):
    """问题抽取的模型调用或输出解析失败。"""


def _parse_raw_json(raw: object) -> Optional[dict]:
    """从非结构化输出中提取首个 JSON 对象。"""
    if not isinstance(raw, str) or not raw:
        return None
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


class EntityExtractor:
    def __init__(self, llm=None, config: dict | None = None):
        self.llm = llm
        self.config = config
        self._chain: Optional[Runnable] = None

    def _get_chain(self) -> Runnable:
        if self.llm is None:
            self.llm = build_llm(for_extraction=True, **({"config": self.config} if self.config is not None else {}))
        if self._chain is None:
            prompt = ChatPromptTemplate.from_messages(
                [SystemMessage(content=EXTRACTION_SYSTEM_PROMPT), ("human", "文本：\n{text}")]
            )
            method = (self.config if self.config is not None else fresh_llm_config())["structured_output_method"]
            self._chain = prompt | self.llm.with_structured_output(
                ChunkExtraction,
                method=method,
                include_raw=True,
            )
        return self._chain

    def extract(self, text: str) -> Optional[ChunkExtraction]:
        chain = self._get_chain()
        try:
            result = chain.invoke({"text": text})
        except (APIError, OutputParserException) as exc:
            logger.warning("实体抽取调用失败: %s", type(exc).__name__)
            return None
        # with_structured_output include_raw=True 返回 {"raw":..., "parsed":...}
        parsed = result.get("parsed") if isinstance(result, dict) else result
        if parsed is None:
            raw = getattr(result.get("raw"), "content", None) if isinstance(result, dict) else None
            parsed = _parse_raw_json(raw)
        try:
            return ChunkExtraction.model_validate(parsed)
        except ValidationError:
            logger.warning("实体抽取输出无法解析或不符合实体关系结构，跳过该片段")
            return None


class QueryEntityExtractor:
    def __init__(self, llm=None):
        self.llm = llm
        self._chain: Optional[Runnable] = None

    def _get_chain(self) -> Runnable:
        if self.llm is None:
            self.llm = build_llm(for_extraction=True)
        if self._chain is None:
            prompt = ChatPromptTemplate.from_messages(
                [SystemMessage(content=QUERY_EXTRACTION_PROMPT), ("human", "问题：{text}")]
            )
            self._chain = prompt | self.llm.with_structured_output(
                QueryEntities,
                method=fresh_llm_config()["structured_output_method"],
                include_raw=True,
            )
        return self._chain

    def extract(self, question: str) -> list:
        chain = self._get_chain()
        try:
            result = chain.invoke({"text": question})
        except (APIError, OutputParserException) as exc:
            logger.warning("问题实体抽取调用失败: %s", type(exc).__name__)
            raise QueryExtractionError("问题实体识别服务调用失败，请稍后重试。") from exc
        parsed = result.get("parsed") if isinstance(result, dict) else result
        if parsed is None:
            raw = getattr(result.get("raw"), "content", None) if isinstance(result, dict) else None
            parsed = _parse_raw_json(raw)
        try:
            return QueryEntities.model_validate(parsed).entities
        except ValidationError as exc:
            logger.warning("问题实体抽取输出无法解析或不符合实体结构")
            raise QueryExtractionError("问题实体识别结果格式错误，请重试。") from exc
