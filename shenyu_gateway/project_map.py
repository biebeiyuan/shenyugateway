from __future__ import annotations

import re
from datetime import datetime
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import Any

from .project_delivery import ProjectDeliveryError, load_delivery_log
from .resident_home import (
    check_manifest,
    current_commit,
    current_revision,
    load_changes,
    load_manifest,
    worktree_dirty,
)
from .runtime import LOCAL_DAY_TZ


ROOT = Path(__file__).resolve().parent.parent

_FLOW_MEANINGS = (
    ("客户端", "你发来的话从这里出发，也从这里收到回答。"),
    ("FastAPI", "先确认身份和请求是否能安全进入家里。"),
    ("ChatRequest", "把这次请求读成网关能够处理的形状。"),
    ("ChatPipeline", "安排这次请求接下来要经过的整条路。"),
    ("prepare_messages", "整理历史、上下文和此刻真正需要带上的记忆。"),
    ("tool merge", "判断要不要使用工具，以及工具应由网关还是客户端完成。"),
    ("UpstreamClient", "把准备好的请求交给模型，并接住持续返回的内容。"),
    ("response capture", "保存该留下的结果、现场证据和下一轮需要的状态。"),
)

_FLOW_ZONES = (
    ("FastAPI", ["zone-1"]),
    ("ChatRequest", ["zone-1", "zone-2"]),
    ("ChatPipeline", ["zone-2"]),
    ("prepare_messages", ["zone-5", "zone-7"]),
    ("tool merge", ["zone-4"]),
    ("UpstreamClient", ["zone-3"]),
    ("response capture", ["zone-2", "zone-7", "zone-8"]),
)


def _read(path: Path, warnings: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(f"暂时读不到 {path.name}：{exc}")
        return ""


def _clean_markdown(value: str) -> str:
    return re.sub(r"`([^`]+)`", r"\1", value.strip()).replace("<br>", " · ")


def _heading_section(text: str, heading: str) -> str:
    start = re.search(rf"^{re.escape(heading)}\s*$", text, flags=re.MULTILINE)
    if not start:
        return ""
    level = len(heading) - len(heading.lstrip("#"))
    rest = text[start.end() :]
    end = re.search(rf"^#{{1,{level}}}\s+", rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def _table_after_heading(text: str, heading: str) -> list[dict[str, str]]:
    section = _heading_section(text, heading)
    lines = [line.strip() for line in section.splitlines()]
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        table_lines: list[str] = []
        for candidate in lines[index:]:
            if not candidate.startswith("|"):
                break
            table_lines.append(candidate)
        if len(table_lines) < 2:
            continue
        headers = [_clean_markdown(cell) for cell in table_lines[0].strip("|").split("|")]
        records: list[dict[str, str]] = []
        for row in table_lines[2:]:
            cells = [_clean_markdown(cell) for cell in row.strip("|").split("|")]
            if len(cells) != len(headers):
                continue
            records.append(dict(zip(headers, cells)))
        return records
    return []


def _bullet_block(section: str, marker: str) -> list[str]:
    try:
        tail = section.split(marker, 1)[1]
    except IndexError:
        return []
    boundary = re.search(r"^(?:\*\*|#{1,6}\s)", tail, flags=re.MULTILINE)
    block = tail[: boundary.start()] if boundary else tail
    return [
        _clean_markdown(match.group(1))
        for line in block.splitlines()
        if (match := re.fullmatch(r"\s*-\s+(.+)", line))
    ]


def _parse_zones(text: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"^## 区域([^：]+)：(.+)$", text, flags=re.MULTILINE))
    zones: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.end() : end]
        responsibilities = _bullet_block(section, "**职责**")
        core_files = _bullet_block(section, "**核心文件**")
        zones.append(
            {
                "id": f"zone-{index + 1}",
                "number": match.group(1).strip(),
                "title": match.group(2).strip(),
                "summary": responsibilities[0] if responsibilities else "",
                "responsibilities": responsibilities,
                "core_files": core_files,
                "component_ids": [],
            }
        )
    return zones


def _flow_meaning(label: str, *, is_last: bool) -> str:
    if is_last and label == "客户端":
        return "整理好的回答回到你正在使用的客户端。"
    for prefix, meaning in _FLOW_MEANINGS:
        if label.startswith(prefix):
            return meaning
    return "这一站承接上一段结果，再把请求交给下一段。"


def _flow_zones(label: str) -> list[str]:
    for prefix, zone_ids in _FLOW_ZONES:
        if label.startswith(prefix):
            return zone_ids
    return []


def _parse_request_flow(text: str) -> list[dict[str, Any]]:
    section = _heading_section(text, "## 总体请求链")
    fenced = re.search(r"```text\s*\n(.*?)\n```", section, flags=re.DOTALL)
    if not fenced:
        return []

    stages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in fenced.group(1).splitlines():
        if not raw_line.strip():
            continue
        leading = len(raw_line) - len(raw_line.lstrip(" "))
        label = raw_line.strip()
        if label.startswith("->"):
            label = label[2:].strip()
            depth = max(1, ((leading - 2) // 5) + 1)
        else:
            depth = 0
        label = _clean_markdown(label)
        if depth <= 1:
            current = {
                "id": f"flow-{len(stages) + 1}",
                "label": label,
                "meaning": "",
                "zone_ids": _flow_zones(label),
                "details": [],
            }
            stages.append(current)
        elif current is not None:
            current["details"].append(label)

    for index, stage in enumerate(stages):
        stage["meaning"] = _flow_meaning(stage["label"], is_last=index == len(stages) - 1)
    return stages


def _path_matches(mapped_file: str, core_entry: str) -> bool:
    if core_entry.endswith("/"):
        return mapped_file.startswith(core_entry)
    if any(marker in core_entry for marker in "*?["):
        return PurePosixPath(mapped_file).match(core_entry)
    core = core_entry.rstrip("/")
    return mapped_file == core or mapped_file.endswith(f"/{core}")


def _component_connections(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    file_owner_counts: dict[str, int] = {}
    for component in components:
        for path in set(component["files"]):
            file_owner_counts[path] = file_owner_counts.get(path, 0) + 1

    connections: list[dict[str, Any]] = []
    for left, right in combinations(components, 2):
        shared = sorted(
            path
            for path in set(left["files"]) & set(right["files"])
            if file_owner_counts[path] == 2
        )
        if not shared:
            continue
        names = "、".join(Path(path).name for path in shared[:3])
        if len(shared) > 3:
            names += f" 等 {len(shared)} 处"
        connections.append(
            {
                "id": f"{left['id']}--{right['id']}",
                "left_id": left["id"],
                "right_id": right["id"],
                "via_files": shared,
                "meaning": f"它们共同经过 {names}，改动这些位置时需要一起确认。",
            }
        )
    return connections


def project_map_snapshot(*, root: Path = ROOT) -> dict[str, Any]:
    warnings: list[str] = []
    manifest = load_manifest(root / "resident_home_manifest.json")
    statuses = check_manifest(manifest, root=root)

    components: list[dict[str, Any]] = []
    for status in statuses:
        source = manifest["components"][status["id"]]
        components.append(
            {
                "id": status["id"],
                "title": status["title"],
                "status": status["status"],
                "summary": source.get("summary", ""),
                "resident_effect": source.get("resident_effect", ""),
                "core": source.get("core", []),
                "files": status.get("files", []),
                "reviewed": status.get("reviewed", {}),
                "zone_ids": [],
            }
        )

    system_zones = _read(root / "docs/architecture/SYSTEM_ZONES.md", warnings)
    readme = _read(root / "README.md", warnings)
    docs_map = _read(root / "DOCS_MAP.md", warnings)
    zones = _parse_zones(system_zones)
    request_flow = _parse_request_flow(system_zones)
    bridges = _table_after_heading(system_zones, "## 跨区关键桥梁")
    products = _table_after_heading(readme, "### 按产品对象反查")
    documents = _table_after_heading(docs_map, "## 现行文档")
    try:
        deliveries = load_delivery_log(root / "project_delivery_log.jsonl")[:60]
    except ProjectDeliveryError as exc:
        deliveries = []
        warnings.append(f"最近施工记录暂时读不到：{exc}")

    if system_zones and not zones:
        warnings.append("SYSTEM_ZONES.md 里暂时没有读到系统分区。")
    if system_zones and not request_flow:
        warnings.append("SYSTEM_ZONES.md 里暂时没有读到总体请求链。")
    if system_zones and not bridges:
        warnings.append("SYSTEM_ZONES.md 里暂时没有读到跨区桥梁。")
    if readme and not products:
        warnings.append("README.md 里暂时没有读到产品反查表。")
    if docs_map and not documents:
        warnings.append("DOCS_MAP.md 里暂时没有读到现行文档表。")

    products_by_name = {
        str(product.get("产品对象") or "").strip(): product
        for product in products
        if str(product.get("产品对象") or "").strip()
    }
    mapped_deliveries: list[dict[str, Any]] = []
    for delivery in deliveries:
        product = products_by_name.get(delivery["product"])
        if product is None:
            warnings.append(f"施工记录产品“{delivery['product']}”尚未进入 README 产品反查表。")
        zone_ids = [
            zone["id"]
            for zone in zones
            if any(
                _path_matches(path, core_entry)
                for path in delivery["paths"]
                for core_entry in zone["core_files"]
            )
        ]
        mapped_deliveries.append(
            {
                **delivery,
                "product_map": product or {},
                "zone_ids": zone_ids,
            }
        )

    for zone in zones:
        component_ids = [
            component["id"]
            for component in components
            if any(
                _path_matches(mapped_file, core_entry)
                for mapped_file in component["files"]
                for core_entry in zone["core_files"]
            )
        ]
        zone["component_ids"] = component_ids
        for component in components:
            if component["id"] in component_ids:
                component["zone_ids"].append(zone["id"])

    changes = list(reversed(load_changes(root / "resident_home_changes.jsonl")))[:24]
    reviewed_at = [
        str((component.get("reviewed") or {}).get("reviewed_at") or "")
        for component in components
    ]
    confirmed = sum(component["status"] == "ok" for component in components)
    pending = sum(component["status"] == "review_required" for component in components)
    errors = sum(component["status"] == "error" for component in components)
    now = datetime.now(LOCAL_DAY_TZ).replace(microsecond=0).isoformat()

    return {
        "ok": True,
        "live": {
            "commit": current_commit(root),
            "revision": current_revision(root),
            "worktree_dirty": worktree_dirty(root),
            "observed_at": now,
            "last_confirmed_at": max(reviewed_at, default=""),
        },
        "summary": {
            "status": "attention" if pending or errors or warnings else "confirmed",
            "component_count": len(components),
            "confirmed_count": confirmed,
            "pending_count": pending,
            "error_count": errors,
            "zone_count": len(zones),
            "bridge_count": len(bridges),
            "document_count": len(documents),
            "delivery_count": len(mapped_deliveries),
            "delivery_product_count": len({item["product"] for item in mapped_deliveries}),
        },
        "components": components,
        "zones": zones,
        "request_flow": request_flow,
        "bridges": bridges,
        "component_bridges": _component_connections(components),
        "documents": documents,
        "products": products,
        "deliveries": mapped_deliveries,
        "changes": changes,
        "warnings": warnings,
    }
