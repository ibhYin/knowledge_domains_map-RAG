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
        self.typed_map: dict[tuple[str, str], str] = {}

    def prepare(self, entities) -> None:
        claims: dict[tuple[str, str], set[str]] = {}
        for ent in entities:
            name, kind = normalize(ent.name), ent.type.value
            claims.setdefault((kind, name), set())
            for alias in ent.aliases:
                alias = normalize(alias)
                if alias and alias != name:
                    claims.setdefault((kind, alias), set()).add(name)
        candidates: dict[str, set[str]] = {}
        for (kind, name) in sorted(claims):
            root, visited = name, []
            while len(claims.get((kind, root), set())) == 1 and root not in visited:
                visited.append(root)
                root = next(iter(claims[kind, root]))
            if root in visited:
                root = min(visited[visited.index(root):])
            key = json.dumps([kind, root], ensure_ascii=False, separators=(",", ":"))
            self.typed_map[kind, name] = key
            candidates.setdefault(name, set()).add(key)
        ambiguous = {name for (_, name), targets in claims.items() if len(targets) > 1}
        self.alias_map = {name: next(iter(keys)) for name, keys in candidates.items()
                          if len(keys) == 1 and name not in ambiguous}

    def entity_key(self, name: str, kind: str) -> str:
        return self.typed_map[kind, normalize(name)]

    def canonical_key(self, name: str) -> str:
        norm = normalize(name)
        return self.alias_map.get(norm, norm)

    def to_dict(self) -> dict[str, str]:
        return dict(self.alias_map)
import json
