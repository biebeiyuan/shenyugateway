from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def isolated_preview_env(*, port: int, db_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHON_DOTENV_DISABLED": "1",
            "PORT": str(port),
            "GATEWAY_DB_PATH": str(db_path),
            "GATEWAY_API_KEY": "",
            "SUPABASE_URL": "",
            "SUPABASE_SERVICE_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "ENABLE_CHAT_ARCHIVE": "false",
            "ENABLE_HEARTBEAT_ARCHIVE": "false",
            "HEARTBEAT_ARCHIVE_RECONCILE_DELETIONS": "false",
            "ENABLE_RECALL_SYNC_WORKER": "false",
            "ENABLE_RECALL_EMBEDDING_WORKER": "false",
            "ENABLE_RECALL_EMBEDDINGS": "false",
        }
    )
    return env


def lan_ipv4_addresses() -> list[str]:
    """手机直连用的局域网地址；WSL mirrored 模式下 hostname -I 会带上宿主机地址。"""
    try:
        import subprocess

        raw = subprocess.check_output(["hostname", "-I"], text=True, timeout=3)
    except Exception:
        return []
    return [part for part in raw.split() if part.count(".") == 3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the built Admin UI without real data or background workers.")
    parser.add_argument("--port", type=int, default=18112)
    parser.add_argument("--db-path", type=Path, default=Path("/tmp/shenyu-admin-preview.db"))
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="绑定地址；用 0.0.0.0 让同一 Wi-Fi 下的手机直接打开（演示模式不需要任何凭据）",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    env = isolated_preview_env(port=args.port, db_path=args.db_path)
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "gateway:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    print(f"Isolated Admin preview: http://127.0.0.1:{args.port}/admin/", flush=True)
    if args.host == "0.0.0.0":
        for ip in lan_ipv4_addresses():
            print(f"  手机同一 Wi-Fi 打开（演示数据）: http://{ip}:{args.port}/admin/?demo=1#/", flush=True)
        print(
            "  手机打不开（拒绝访问）时：WSL mirrored 模式下 Windows 防火墙会拦局域网入站，"
            "需一次性放行——管理员 PowerShell 跑：New-NetFirewallRule -DisplayName "
            f"ShenyuAdminPreview{args.port} -Direction Inbound -Protocol TCP -LocalPort {args.port} -Action Allow",
            flush=True,
        )
    os.chdir(ROOT)
    os.execvpe(sys.executable, command, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
