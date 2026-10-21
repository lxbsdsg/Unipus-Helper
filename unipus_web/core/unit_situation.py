"""单元学习进度（unitTaskSituation）解析。"""

from __future__ import annotations

import json

from ..models import SituationNode, as_bool, as_float, as_int, as_str, lenient_obj


class UnitSituation:
    def __init__(self) -> None:
        self.nodes: list[SituationNode] = []
        self._by_path: dict[str, SituationNode] = {}
        self._by_node_id: dict[str, SituationNode] = {}

    @classmethod
    def parse(cls, payload: dict | str | None) -> "UnitSituation":
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        root = lenient_obj(payload)
        situation = cls()
        value = lenient_obj(root.get("value"))
        items = value.get("list")
        if isinstance(items, list):
            for item in items:
                node = situation._parse_node(item)
                situation.nodes.append(node)
                situation._index(node)
        return situation

    def _parse_node(self, data) -> SituationNode:
        d = lenient_obj(data)
        node = SituationNode(
            node_id=as_str(d.get("nodeId")),
            caption=as_str(d.get("caption")),
            name=as_str(d.get("name")),
            path=as_str(d.get("path")),
            role=as_str(d.get("role")),
            finish_progress=as_float(d.get("finishProgress")),
            duration=as_int(d.get("duration")),
            required=as_bool(d.get("required")),
            score_task_flag=as_bool(d.get("scoreTaskFlag")),
        )
        children = d.get("children")
        if isinstance(children, list):
            node.children = [self._parse_node(child) for child in children]
        return node

    def _index(self, node: SituationNode) -> None:
        if node.path:
            self._by_path[node.path] = node
        if node.node_id:  # 空串不建索引，避免误命中
            self._by_node_id[node.node_id] = node
        for child in node.children:
            self._index(child)

    def get_node_by_node_id(self, node_id: str | None) -> SituationNode | None:
        if not node_id:
            return None
        return self._by_node_id.get(node_id)

    def get_node_by_path(self, path: str | None) -> SituationNode | None:
        if not path:
            return None
        return self._by_path.get(path)
