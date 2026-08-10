from __future__ import annotations

import asyncio
from pathlib import Path

import shenyu_gateway.archive_routes as archive_routes
from shenyu_gateway.archive_routes import ArchiveRouteDeps, build_archive_router
from shenyu_gateway.project_map import _component_connections, project_map_snapshot
from shenyu_gateway.resident_books import render_bookshelf_overview


ROOT = Path(__file__).resolve().parent.parent


def test_component_connections_keep_pairwise_files_but_ignore_multi_owner_hubs():
    components = [
        {"id": "stars", "files": ["shared/direct.py", "shared/hub.py", "shared/direct.py"]},
        {"id": "mem", "files": ["shared/direct.py", "shared/hub.py", "shared/mem.py"]},
        {"id": "room", "files": ["shared/hub.py", "shared/room.py"]},
    ]

    assert _component_connections(components) == [
        {
            "id": "stars--mem",
            "left_id": "stars",
            "right_id": "mem",
            "via_files": ["shared/direct.py"],
            "meaning": "它们共同经过 direct.py，改动这些位置时需要一起确认。",
        }
    ]


def test_project_map_assembles_live_authorities_and_connections():
    snapshot = project_map_snapshot(root=ROOT)

    assert snapshot["ok"] is True
    assert snapshot["summary"]["zone_count"] == 8
    assert snapshot["summary"]["component_count"] == 8
    assert snapshot["request_flow"][0]["label"] == "客户端"
    assert snapshot["request_flow"][-1]["meaning"] == "整理好的回答回到你正在使用的客户端。"
    assert any(bridge["桥梁"] == "context_builder.py" for bridge in snapshot["bridges"])
    assert any(document["文档"] == "DOCS_MAP.md" for document in snapshot["documents"])
    assert any(product["产品对象"] == "共享书架" for product in snapshot["products"])
    assert snapshot["summary"]["delivery_count"] >= 5
    assert snapshot["summary"]["delivery_product_count"] >= 3
    pwa_delivery = next(item for item in snapshot["deliveries"] if item["product"] == "PWA 聊天端")
    assert pwa_delivery["product_map"]["产品对象"] == "PWA 聊天端"
    stars = next(component for component in snapshot["components"] if component["id"] == "stars")
    assert "zone-6" in stars["zone_ids"]

    stars_mem = next(
        connection
        for connection in snapshot["component_bridges"]
        if {connection["left_id"], connection["right_id"]} == {"stars", "mem"}
    )
    assert stars_mem["via_files"] == ["shenyu_gateway/memory_island.py"]
    assert all(
        "shenyu_gateway/context_builder.py" not in connection["via_files"]
        for connection in snapshot["component_bridges"]
    )
    assert snapshot["warnings"] == []


def test_project_map_has_a_separate_admin_route_and_never_enters_bookshelf_context(monkeypatch):
    expected = {"ok": True, "summary": {"status": "confirmed"}}
    monkeypatch.setattr(archive_routes, "project_map_snapshot", lambda: expected)
    router = build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: None))
    endpoints = {route.path: route.endpoint for route in router.routes}

    assert asyncio.run(endpoints["/api/project-map"]()) == expected
    rendered = render_bookshelf_overview(
        {
            "home": {"current_week_changes": 0},
            "identity": None,
            "origin_books": [],
            "project_map": expected,
        }
    )
    assert "家里地图" not in rendered
    assert "project" not in rendered.lower()


def test_production_image_carries_the_map_authorities():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY README.md DOCS_MAP.md ./" in dockerfile
    assert "project_delivery_log.jsonl" in dockerfile
    assert "COPY docs/architecture/SYSTEM_ZONES.md ./docs/architecture/SYSTEM_ZONES.md" in dockerfile
