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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the built Admin UI without real data or background workers.")
    parser.add_argument("--port", type=int, default=18112)
    parser.add_argument("--db-path", type=Path, default=Path("/tmp/shenyu-admin-preview.db"))
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
        "127.0.0.1",
        "--port",
        str(args.port),
    ]
    print(f"Isolated Admin preview: http://127.0.0.1:{args.port}/admin/", flush=True)
    os.chdir(ROOT)
    os.execvpe(sys.executable, command, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
