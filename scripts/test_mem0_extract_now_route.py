from __future__ import annotations

from fastapi.testclient import TestClient

import gateway


def main() -> None:
    old_gateway_key = gateway.cfg.gateway_key
    old_extract_now = gateway.AtomicMemoryService.extract_now

    async def fake_extract_now(self, session_tag, source_model=""):
        return {
            "ok": True,
            "session_tag": session_tag or "default",
            "source_model": source_model or "manual",
        }

    gateway.cfg.gateway_key = ""
    gateway.AtomicMemoryService.extract_now = fake_extract_now
    try:
        with TestClient(gateway.app) as client:
            post_response = client.post(
                "/api/mem0/extract-now",
                json={"session_tag": "default", "model": "route-test-model"},
            )
            assert post_response.status_code == 200, post_response.text
            assert post_response.json() == {
                "ok": True,
                "session_tag": "default",
                "source_model": "route-test-model",
            }

            get_response = client.get("/api/mem0/extract-now")
            assert get_response.status_code == 405, get_response.text
    finally:
        gateway.AtomicMemoryService.extract_now = old_extract_now
        gateway.cfg.gateway_key = old_gateway_key


if __name__ == "__main__":
    main()
    print("mem0 extract-now route test passed")
