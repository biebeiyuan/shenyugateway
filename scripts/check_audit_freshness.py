"""Print non-blocking freshness warnings for confirmed audit records."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = ROOT / "docs" / "architecture" / "AUDIT_MATRIX.md"
SECTION_HEADING = "## 已确认修改"
METADATA_RE = re.compile(
    r"^- 最近复核：(\d{4}-\d{2}-\d{2})；关联路径：(.*)$"
)


@dataclass(frozen=True)
class AuditEntry:
    title: str
    reviewed_on: date | None
    paths: tuple[str, ...]


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _confirmed_entries() -> list[AuditEntry]:
    lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(SECTION_HEADING) + 1
    except ValueError:
        return []

    entries: list[AuditEntry] = []
    title: str | None = None
    body: list[str] = []

    def append_current() -> None:
        if title is None:
            return
        metadata_line = next(
            (line for line in body if line.startswith("- 最近复核：")),
            "",
        )
        match = METADATA_RE.fullmatch(metadata_line)
        if not match:
            entries.append(AuditEntry(title, None, ()))
            return
        try:
            reviewed_on = date.fromisoformat(match.group(1))
        except ValueError:
            entries.append(AuditEntry(title, None, ()))
            return
        paths = tuple(re.findall(r"`([^`]+)`", match.group(2)))
        entries.append(AuditEntry(title, reviewed_on, paths))

    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.startswith("### "):
            append_current()
            title = line.removeprefix("### ").strip()
            body = []
            continue
        if title is not None:
            body.append(line)
    append_current()
    return entries


def _warnings(entries: list[AuditEntry]) -> list[str]:
    warnings: list[str] = []
    if not entries:
        return [f"{AUDIT_PATH.relative_to(ROOT)} 缺少“已确认修改”记录"]

    for entry in entries:
        if entry.reviewed_on is None or not entry.paths:
            warnings.append(f"{entry.title}：缺少固定格式的最近复核日期或关联路径")
            continue

        for relative_path in entry.paths:
            path = ROOT / relative_path
            if not path.exists():
                warnings.append(f"{entry.title}：关联路径不存在：{relative_path}")
                continue

            try:
                dirty = _run_git(
                    "status",
                    "--short",
                    "--untracked-files=all",
                    "--",
                    relative_path,
                )
                last_changed = _run_git(
                    "log",
                    "-1",
                    "--format=%cs",
                    "--",
                    relative_path,
                )
            except RuntimeError as exc:
                warnings.append(f"{entry.title}：无法读取 Git 状态：{exc}")
                continue

            if dirty:
                warnings.append(f"{entry.title}：关联路径当前有未提交改动：{relative_path}")
            if not last_changed:
                warnings.append(f"{entry.title}：关联路径尚无 Git 修改日期：{relative_path}")
                continue

            try:
                changed_on = date.fromisoformat(last_changed)
            except ValueError:
                warnings.append(
                    f"{entry.title}：无法解析 {relative_path} 的 Git 日期：{last_changed}"
                )
                continue
            if changed_on > entry.reviewed_on:
                warnings.append(
                    f"{entry.title}：{relative_path} 最近修改于 {changed_on}，"
                    f"晚于复核日期 {entry.reviewed_on}"
                )
    return warnings


def main() -> int:
    try:
        warnings = _warnings(_confirmed_entries())
    except Exception as exc:  # Manual warning tool: never turn parser trouble into CI red.
        warnings = [f"检查器自身无法完成读取：{exc}"]
    if not warnings:
        print("AUDIT_MATRIX 新鲜度检查：没有黄灯提醒。")
        return 0

    label = "\033[33m黄灯\033[0m" if sys.stdout.isatty() else "黄灯"
    print(f"AUDIT_MATRIX 新鲜度检查：{len(warnings)} 条{label}提醒。")
    for warning in warnings:
        print(f"- [{label}] {warning}")
    print("这些提醒只表示关联文件后来动过或正在修改，不代表确认记录已经失效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
