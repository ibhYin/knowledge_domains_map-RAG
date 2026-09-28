import re
import unicodedata

_STRIP_CHARS = "。，、；：！？()（）[]【】\"“”'‘’…—"


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"\s+", "", s)
    return s.strip(_STRIP_CHARS).lower()


class EntityResolver:
    """别名 → 规范 key 注册表。canonical_key 决定图节点的主键。"""

    def __init__(self, alias_map: dict[str, str] | None = None):
        self.alias_map = alias_map or {}

    def canonical_key(self, name: str) -> str:
        norm = normalize(name)
        return self.alias_map.get(norm, norm)

    def register_aliases(self, name: str, aliases: list[str]) -> str:
        key = self.canonical_key(name)
        if key != normalize(name):
            self.alias_map.setdefault(normalize(name), key)
        for alias in aliases:
            norm = normalize(alias)
            if norm:
                self.alias_map.setdefault(norm, key)
        return key

    def to_dict(self) -> dict[str, str]:
        return dict(self.alias_map)
