from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class EntityType(str, Enum):
    PERSON = "PERSON"
    ORG = "ORG"
    LOCATION = "LOCATION"
    CONCEPT = "CONCEPT"
    TIME = "TIME"
    EVENT = "EVENT"


class RelationType(str, Enum):
    MEMBER_OF = "MEMBER_OF"
    AFFILIATED_WITH = "AFFILIATED_WITH"
    FOUNDED_BY = "FOUNDED_BY"
    CREATED = "CREATED"
    LOCATED_IN = "LOCATED_IN"
    RELATED_TO = "RELATED_TO"
    CAUSES = "CAUSES"
    AFFECTS = "AFFECTS"
    PROPOSED_BY = "PROPOSED_BY"
    INVENTED_BY = "INVENTED_BY"
    PARTNERS_WITH = "PARTNERS_WITH"
    USES = "USES"
    IN_PERIOD = "IN_PERIOD"


# 枚举 → 中文标签，用于上下文格式化与前端展示
ENTITY_TYPE_CN = {
    EntityType.PERSON: "人物",
    EntityType.ORG: "组织",
    EntityType.LOCATION: "地点",
    EntityType.CONCEPT: "概念",
    EntityType.TIME: "时间",
    EntityType.EVENT: "事件",
}

RELATION_TYPE_CN = {
    RelationType.MEMBER_OF: "隶属",
    RelationType.AFFILIATED_WITH: "任职",
    RelationType.FOUNDED_BY: "创建",
    RelationType.CREATED: "提出/发布",
    RelationType.LOCATED_IN: "位于",
    RelationType.RELATED_TO: "相关",
    RelationType.CAUSES: "导致",
    RelationType.AFFECTS: "影响",
    RelationType.PROPOSED_BY: "提出者",
    RelationType.INVENTED_BY: "发明者",
    RelationType.PARTNERS_WITH: "合作",
    RelationType.USES: "使用",
    RelationType.IN_PERIOD: "时间归属",
}


class Entity(BaseModel):
    name: str
    type: EntityType
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class Relation(BaseModel):
    source: str
    target: str
    relation: RelationType
    description: str = ""

    @model_validator(mode="after")
    def _check_not_self(self):
        if self.source == self.target:
            raise ValueError(f"关系不能连接同一实体: {self.source}")
        return self


class ChunkExtraction(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class QueryEntity(BaseModel):
    name: str
    type: Optional[EntityType] = None


class QueryEntities(BaseModel):
    entities: list[QueryEntity] = Field(default_factory=list)
