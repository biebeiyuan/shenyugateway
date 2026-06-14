from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse


ADMIN_PROTECTED_PREFIXES = ("/api/",)


async def admin_auth_middleware_handler(request: Request, call_next, *, cfg: Any):
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    needs_auth = any(path.startswith(p) for p in ADMIN_PROTECTED_PREFIXES)
    if path.startswith("/admin"):
        needs_auth = True

    if needs_auth and cfg.gateway_key:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        if not token:
            token = request.query_params.get("token", "")
        if not token:
            token = request.cookies.get("shenyu_token", "")

        if token != cfg.gateway_key:
            accept = request.headers.get("Accept", "")
            if "text/html" in accept:
                return HTMLResponse(login_page_html(), status_code=401)
            return JSONResponse(status_code=401, content={"error": "Unauthorized. Set GATEWAY_API_KEY or pass ?token=xxx"})

    return await call_next(request)


async def verify_api_key(request: Request, *, cfg: Any):
    auth = request.headers.get("Authorization", "")
    if cfg.gateway_key:
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing API key")
        if auth.removeprefix("Bearer ") != cfg.gateway_key:
            raise HTTPException(status_code=401, detail="Invalid API key")


def login_page_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>沈予网关 · 登录</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',sans-serif;background:#0f1117;color:#e1e4e8;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:32px;width:340px;text-align:center}
.box h2{color:#8b5cf6;margin-bottom:8px;font-size:18px}
.box p{color:#7d8590;font-size:12px;margin-bottom:20px}
.box input{width:100%;background:#0d1117;border:1px solid #30363d;color:#e1e4e8;padding:10px 14px;border-radius:8px;font-size:14px;margin-bottom:12px}
.box input:focus{outline:none;border-color:#8b5cf6}
.box button{width:100%;background:#8b5cf6;border:none;color:#fff;padding:10px;border-radius:8px;font-size:14px;cursor:pointer}
.box button:hover{background:#7c3aed}
.err{color:#f85149;font-size:12px;margin-top:8px;display:none}
</style></head><body>
<div class="box">
  <h2>沈予网关</h2>
  <p>请输入管理密钥</p>
  <input id="pw" type="password" placeholder="GATEWAY_API_KEY" autofocus
    onkeydown="if(event.key==='Enter')doLogin()">
  <button onclick="doLogin()">进入</button>
  <div class="err" id="err">密钥错误</div>
</div>
<script>
function doLogin(){
  const pw=document.getElementById('pw').value.trim();
  if(!pw) return;
  document.cookie='shenyu_token='+encodeURIComponent(pw)+';path=/;max-age=86400;SameSite=Lax';
  localStorage.setItem('shenyu_token',pw);
  location.reload();
}
</script>
</body></html>"""
