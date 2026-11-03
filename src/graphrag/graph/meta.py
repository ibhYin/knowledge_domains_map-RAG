"""图谱 meta 键名常量。

meta 仍是普通 dict（graph.json / meta.json 存储格式不变），但代码读写
统一走 MetaKeys 命名空间，消除散落在各层的字符串字面量。
"""


class MetaKeys:
    ALIAS_MAP = "alias_map"
    PROCESSED_CHUNKS = "processed_chunks"
    EXTRACTION_FINGERPRINT = "extraction_fingerprint"
    GRAPH_VERSION = "graph_version"
    DELETED_DOCUMENTS = "deleted_documents"
    BUILT_AT = "built_at"
    STATS = "stats"
    MODEL = "model"
