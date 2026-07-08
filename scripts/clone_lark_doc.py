#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clone a readable Lark/Feishu Docx or Wiki document into the current user's space.

This is an open, hackable framework. It intentionally uses lark-cli shortcuts
instead of private reverse-engineered APIs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_PARENT_POSITION = "my_library"
OUTPUT_ROOT = Path(os.environ.get("LARK_DOC_CLONER_OUTPUT_ROOT", Path(tempfile.gettempdir()) / "LarkDocCloner"))
INSTALL_GUIDE_URL = "https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md"


class CloneError(RuntimeError):
    pass


def decode_output(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gb18030", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def run_lark(
    args: list[str],
    profile: str | None = None,
    check: bool = True,
    cwd: Path | None = None,
) -> dict[str, Any]:
    executable = resolve_lark_cli()
    cmd = [executable]
    if profile:
        cmd.extend(["--profile", profile])
    cmd.extend(args)

    proc = subprocess.run(cmd, capture_output=True, cwd=str(cwd) if cwd else None)
    stdout = decode_output(proc.stdout)
    stderr = decode_output(proc.stderr)
    payload: Any = None
    stripped = stdout.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None

    result = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "json": payload,
    }
    if check and proc.returncode != 0:
        raise CloneError(f"Command failed: {' '.join(cmd)}\n{stderr or stdout}")
    return result


def ensure_lark_cli() -> None:
    if not resolve_lark_cli():
        raise CloneError(install_help_text())


def install_help_text() -> str:
    return (
        "未找到 lark-cli。请先安装飞书 CLI。\n"
        f"官方安装文档：{INSTALL_GUIDE_URL}\n"
        "如果你同意由 Agent 自动安装，可让 Agent 执行：npm install -g @larksuite/cli\n"
        "安装后运行：lark-cli auth login"
    )


def resolve_lark_cli() -> str:
    configured = os.environ.get("LARK_CLI") or os.environ.get("XUEJIAN_LARK_CLI")
    if configured and Path(configured).exists():
        return configured
    for candidate in ("lark-cli.cmd", "lark-cli.exe", "lark-cli"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "lark-cli"


def check_environment(profile: str | None = None) -> dict[str, Any]:
    ensure_lark_cli()
    version = run_lark(["--version"], profile=profile, check=False)
    profiles = run_lark(["profile", "list"], profile=profile, check=False)
    whoami = run_lark(["whoami", "--json"], profile=profile, check=False)
    return {
        "version": version,
        "profiles": profiles,
        "whoami": whoami,
    }


def has_usable_profile(env: dict[str, Any]) -> tuple[bool, str]:
    profiles = env["profiles"].get("json")
    if not isinstance(profiles, list) or not profiles:
        return False, "没有找到 lark-cli profile。请先运行 lark-cli auth login。"
    active = next((item for item in profiles if item.get("active")), profiles[0])
    token_status = active.get("tokenStatus")
    if token_status and token_status not in {"ok", "valid", "active"}:
        return False, f"profile 存在，但 tokenStatus={token_status}。请运行 lark-cli auth login 刷新登录。"
    return True, ""


def slugify(value: str) -> str:
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return value[:80] or "document"


def make_output_dir(doc: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = OUTPUT_ROOT / f"{stamp}-{slugify(doc)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_document(fetch_payload: dict[str, Any]) -> dict[str, Any]:
    data = fetch_payload.get("data") if isinstance(fetch_payload, dict) else None
    document = data.get("document") if isinstance(data, dict) else None
    if not isinstance(document, dict):
        raise CloneError("docs +fetch 返回中没有 data.document。")
    content = document.get("content")
    if not isinstance(content, str) or not content.strip():
        raise CloneError("docs +fetch 返回中没有可复刻的 content。")
    return document


def extract_title(inspect_payload: dict[str, Any], document: dict[str, Any], suffix: str) -> str:
    candidates: list[str] = []
    for root in (inspect_payload.get("data"), inspect_payload):
        if isinstance(root, dict):
            for key in ("title", "name"):
                value = root.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
            obj = root.get("document")
            if isinstance(obj, dict):
                value = obj.get("title") or obj.get("name")
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
    xml = document.get("content") or ""
    match = re.search(r"<title(?:\s[^>]*)?>(.*?)</title>", xml, flags=re.S | re.I)
    if match:
        title_text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if title_text:
            candidates.append(title_text)
    base = candidates[0] if candidates else "Clone Document"
    if suffix and not base.endswith(suffix):
        return base + suffix
    return base


def normalize_xml(content: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    xml = content.strip()

    # Block IDs belong to the source document. Reusing them in a new document is
    # noisy at best and invalid at worst.
    xml = re.sub(r'\s+id="[^"]*"', "", xml)
    xml = re.sub(r"\s+id='[^']*'", "", xml)

    # Full fetch should not produce <fragment>, but fetch-only variants might.
    xml = re.sub(r"^<fragment\b[^>]*>", "", xml, flags=re.I).strip()
    xml = re.sub(r"</fragment>$", "", xml, flags=re.I).strip()

    # Prefer network href for image recreation when the fetch payload exposes URL.
    def img_rewrite(match: re.Match[str]) -> str:
        tag = match.group(0)
        if " href=" in tag:
            return tag
        url_match = re.search(r'\surl="([^"]+)"', tag)
        if url_match:
            insert_at = tag.rfind("/>") if tag.endswith("/>") else tag.rfind(">")
            if insert_at > 0:
                return tag[:insert_at] + f' href="{url_match.group(1)}"' + tag[insert_at:]
        return tag

    xml = re.sub(r"<img\b[^>]*?/?>", img_rewrite, xml, flags=re.I)

    risky_tags = ["sheet", "bitable", "whiteboard", "synced_reference", "synced_source", "task", "okr"]
    for tag in risky_tags:
        if re.search(rf"<{tag}\b", xml, flags=re.I):
            warnings.append(f"检测到 <{tag}> 资源块，新文档中可能需要人工检查。")

    if "<title" not in xml.lower():
        warnings.append("原始 XML 没有 <title>，将使用 inspect 或默认标题创建。")
    else:
        # The script passes --title to docs +create, so keeping <title> in the
        # body would make lark-cli filter a duplicate title. Remove it here and
        # keep the effective title in the command argument.
        xml = re.sub(r"<title\b[^>]*>.*?</title>", "", xml, flags=re.S | re.I).strip()

    return xml + "\n", warnings


def clone_doc(args: argparse.Namespace) -> dict[str, Any]:
    env = check_environment(args.profile)
    ok, reason = has_usable_profile(env)
    if not ok and not args.allow_stale_token:
        raise CloneError(reason)
    if args.check:
        return {"ok": True, "environment": summarize_environment(env), "warning": reason}

    if not args.doc:
        raise CloneError("请提供 --doc 飞书文档链接或 token。")

    output_dir = make_output_dir(args.doc)
    write_json(output_dir / "environment.json", summarize_environment(env))

    inspect = run_lark(["drive", "+inspect", "--url", args.doc, "--json"], profile=args.profile)
    write_json(output_dir / "inspect.json", inspect.get("json") or {"stdout": inspect["stdout"], "stderr": inspect["stderr"]})

    fetch = run_lark(
        [
            "docs",
            "+fetch",
            "--doc",
            args.doc,
            "--scope",
            "full",
            "--detail",
            "full",
            "--doc-format",
            "xml",
            "--as",
            "user",
            "--json",
        ],
        profile=args.profile,
    )
    fetch_payload = fetch.get("json")
    if not isinstance(fetch_payload, dict):
        raise CloneError("docs +fetch 没有返回 JSON。")
    write_json(output_dir / "fetch.json", fetch_payload)

    document = extract_document(fetch_payload)
    raw_xml = document["content"]
    (output_dir / "content.raw.xml").write_text(raw_xml, encoding="utf-8")

    clone_xml, warnings = normalize_xml(raw_xml)
    content_path = output_dir / "content.clone.xml"
    content_path.write_text(clone_xml, encoding="utf-8")

    reference_map = document.get("reference_map")
    reference_map_path = None
    if isinstance(reference_map, dict) and reference_map:
        reference_map_path = output_dir / "reference-map.json"
        write_json(reference_map_path, reference_map)

    title = args.title or extract_title(inspect.get("json") or {}, document, args.title_suffix)

    if args.fetch_only:
        result = {
            "ok": True,
            "mode": "fetch-only",
            "title": title,
            "output_dir": str(output_dir),
            "content_path": str(content_path),
            "warnings": warnings,
        }
        write_json(output_dir / "result.json", result)
        return result

    create_cmd = [
        "docs",
        "+create",
        "--as",
        "user",
        "--doc-format",
        "xml",
        "--title",
        title,
        "--content",
        "@content.clone.xml",
        "--json",
    ]
    if reference_map_path:
        create_cmd.extend(["--reference-map", "@reference-map.json"])
    if args.parent_token:
        create_cmd.extend(["--parent-token", args.parent_token])
    elif args.parent_position:
        create_cmd.extend(["--parent-position", args.parent_position])

    if args.dry_run:
        create_cmd.append("--dry-run")

    create = run_lark(create_cmd, profile=args.profile, cwd=output_dir)
    create_payload = create.get("json")
    write_json(output_dir / "create.json", create_payload or {"stdout": create["stdout"], "stderr": create["stderr"]})

    new_url = None
    if isinstance(create_payload, dict):
        data = create_payload.get("data")
        document_payload = data.get("document") if isinstance(data, dict) else None
        if isinstance(document_payload, dict):
            new_url = document_payload.get("url")
        create_warnings = data.get("warnings") if isinstance(data, dict) else None
        if isinstance(create_warnings, list):
            warnings.extend(str(item) for item in create_warnings)

    result = {
        "ok": bool(new_url) or args.dry_run,
        "mode": "rebuild",
        "source": args.doc,
        "title": title,
        "url": new_url,
        "output_dir": str(output_dir),
        "content_path": str(content_path),
        "warnings": warnings,
    }
    write_json(output_dir / "result.json", result)
    return result


def summarize_environment(env: dict[str, Any]) -> dict[str, Any]:
    profiles_json = env["profiles"].get("json")
    return {
        "version": (env["version"].get("stdout") or env["version"].get("stderr") or "").strip(),
        "profiles": profiles_json if isinstance(profiles_json, list) else None,
        "whoami": env["whoami"].get("json"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clone a readable Lark/Feishu document into the current user's space.")
    parser.add_argument("--doc", help="Lark/Feishu document URL or token.")
    parser.add_argument("--profile", help="lark-cli profile name. Defaults to active profile.")
    parser.add_argument("--parent-position", default=DEFAULT_PARENT_POSITION, help="Target position, e.g. my_library.")
    parser.add_argument("--parent-token", help="Target folder token or wiki parent node token.")
    parser.add_argument("--title", help="Override new document title.")
    parser.add_argument("--title-suffix", default=" - clone", help="Suffix appended to source title.")
    parser.add_argument("--fetch-only", action="store_true", help="Fetch and normalize only; do not create a new document.")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to the create call.")
    parser.add_argument("--check", action="store_true", help="Only check lark-cli and profile status.")
    parser.add_argument("--install-help", action="store_true", help="Print lark-cli installation guidance.")
    parser.add_argument("--allow-stale-token", action="store_true", help="Continue even if profile tokenStatus is not ok.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.install_help:
        print(install_help_text())
        return 0
    try:
        result = clone_doc(args)
    except CloneError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
