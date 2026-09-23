"""Dynamic Action Space 构造。移植自 jev-ultrafast/model.py:action_space()。

关联硬约束：
  D7  Candidate Filter = Dynamic Action Space 的抽象名
  D13 scroll / wait 是 control action
  D14 250 上限由 snapshot.js 保证，本模块不重复

输出三层：
  elements:  [{index, label, role, operations[], value?, options?}, ...]
  targets:   {OPERATION: {target_id: action}}
  controls:  {OPERATION_UPPER: action}

语义与 model.py:action_space() 完全一致。任何差异都是 bug。
"""
from __future__ import annotations


_KIND_TO_OPERATION = {
    "click": "CLICK",
    "fill": "TYPE_TEXT",
    "select": "SELECT",
}


def action_space(actions: list[dict]) -> tuple[list[dict], dict, dict]:
    elements: list[dict] = []
    indices: dict[int, str] = {}
    targets: dict[str, dict[str, dict]] = {}
    controls: dict[str, dict] = {}

    for action in actions:
        kind = action["kind"]
        if kind not in _KIND_TO_OPERATION:
            controls[action["id"].upper()] = action
            continue

        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element: dict = {
                k: action[k]
                for k in ("role", "value", "checked", "selected", "expanded")
                if k in action
            }
            element.update(
                index=index,
                label=action["label"].split(" → ")[0],
                operations=[],
            )
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)

        index = indices[node]
        operation = _KIND_TO_OPERATION[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)

        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append(
                {"index": target, "label": action["label"], "value": action["value"]}
            )
        group[target] = action

    return elements, targets, controls
