from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse


@dataclass(frozen=True)
class AdminShellRouteDeps:
    admin_dist_dir: Path


def build_admin_shell_router(deps: AdminShellRouteDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def root_page():
        return RedirectResponse("/admin")

    @router.get("/admin")
    @router.get("/admin/")
    async def admin_page():
        html_path = deps.admin_dist_dir / "index.html"
        if html_path.exists():
            return FileResponse(html_path)
        return HTMLResponse(
            "<h1>admin dist not found</h1>"
            "<p>Run <code>npm run build</code> in <code>admin/</code>, "
            "or use <code>npm run dev</code> during development.</p>"
        )

    return router
