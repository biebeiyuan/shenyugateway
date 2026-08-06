from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shenyu_gateway.middleware import register_middlewares


def test_pwa_worker_and_build_info_bypass_browser_and_cdn_caches():
    app = FastAPI()

    @app.get("/chat/sw.js")
    async def worker():
        return {"worker": True}

    @app.get("/chat/build-info.json")
    async def build_info():
        return {"build": True}

    @app.get("/chat/assets/index.js")
    async def hashed_bundle():
        return {"bundle": True}

    @app.get("/")
    async def root_page():
        return {"root": True}

    @app.get("/admin")
    async def admin_page():
        return {"admin": True}

    @app.get("/admin/assets/index.js")
    async def admin_hashed_bundle():
        return {"admin_bundle": True}

    register_middlewares(app, SimpleNamespace(gateway_key=""))
    client = TestClient(app)

    for path in ("/chat/sw.js", "/chat/build-info.json", "/", "/admin"):
        response = client.get(path)
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["cdn-cache-control"] == "no-store"

    assert "cache-control" not in client.get("/chat/assets/index.js").headers
    # Hashed admin bundles stay cacheable; only the shell HTML bypasses caches.
    assert "cache-control" not in client.get("/admin/assets/index.js").headers
