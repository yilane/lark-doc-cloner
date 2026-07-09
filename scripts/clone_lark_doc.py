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


DEFAULT_PARENT_TARGET = "drive_root"
OUTPUT_ROOT = Path(os.environ.get("LARK_DOC_CLONER_OUTPUT_ROOT", Path(tempfile.gettempdir()) / "LarkDocCloner"))
INSTALL_GUIDE_URL = "https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md"
CONFIG_PATH = Path(os.environ.get("LARK_DOC_CLONER_CONFIG", Path.home() / ".agents" / "lark-doc-cloner.config.json"))
ATTR_RE = re.compile(r"""([A-Za-z_:\-][\w:.\-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")

KNOWN_STRUCTURE_TAGS = {
    "doc",
    "document",
    "fragment",
    "title",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "text",
    "a",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "code",
    "codeblock",
    "pre",
    "blockquote",
    "quote",
    "callout",
    "hr",
    "br",
    "ul",
    "ol",
    "li",
    "todo",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "img",
    "image",
    "source",
    "file",
    "attachment",
    "mention",
    "docs_link",
}

RISKY_BLOCKS: dict[str, dict[str, str]] = {
    "sheet": {"level": "degraded", "reason": "电子表格资源块通常只能保留引用，不能完整重建表内数据。"},
    "bitable": {"level": "degraded", "reason": "多维表格/Base 需要单独接口复制，XML 重建只能降级。"},
    "base": {"level": "degraded", "reason": "Base 资源块需要单独接口复制，XML 重建只能降级。"},
    "whiteboard": {"level": "degraded", "reason": "画板需要单独下载或重建，XML 创建不保证保真。"},
    "mindnote": {"level": "degraded", "reason": "思维笔记资源需要专门接口处理。"},
    "synced_reference": {"level": "degraded", "reason": "同步块引用依赖源块权限和关系，不能直接复用。"},
    "synced_source": {"level": "degraded", "reason": "同步块源关系不能直接复制到新文档。"},
    "task": {"level": "degraded", "reason": "任务块通常依赖任务系统，重建后需要人工检查。"},
    "okr": {"level": "degraded", "reason": "OKR 块依赖 OKR 系统，重建后需要人工检查。"},
    "slides": {"level": "degraded", "reason": "幻灯片资源需要单独复制或导入。"},
    "wiki": {"level": "check", "reason": "Wiki 引用可能只保留链接，不复制树结构。"},
}

MEDIA_TAGS = {"img", "image", "source", "file", "attachment"}
COPYABLE_TYPES = {"doc", "docx", "sheet", "bitable", "file", "mindnote", "slides"}


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


def first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def dig(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in ATTR_RE.finditer(tag):
        attrs[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3) or ""
    return attrs


def count_tags(xml: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in re.finditer(r"<\s*([A-Za-z][\w:.-]*)\b", xml):
        tag = match.group(1).split(":")[-1].lower()
        counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items()))


def collect_media_assets(xml: str) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for match in re.finditer(r"<\s*([A-Za-z][\w:.-]*)\b[^>]*?/?>", xml, flags=re.S):
        tag_name = match.group(1).split(":")[-1].lower()
        if tag_name not in MEDIA_TAGS:
            continue
        attrs = parse_attrs(match.group(0))
        token = (
            attrs.get("token")
            or attrs.get("file_token")
            or attrs.get("media_token")
            or attrs.get("block_token")
            or attrs.get("id")
        )
        url = attrs.get("href") or attrs.get("url") or attrs.get("src")
        asset_type = "image" if tag_name in {"img", "image"} else "file"
        assets.append(
            {
                "index": len(assets) + 1,
                "anchor": f"LARK_DOC_CLONER_MEDIA_{len(assets) + 1:03d}",
                "tag": tag_name,
                "type": asset_type,
                "token": token,
                "url": url,
                "name": attrs.get("name") or attrs.get("filename") or attrs.get("title"),
                "downloaded": False,
                "download_path": None,
                "status": "pending" if token else ("url-only" if url else "missing-token-and-url"),
            }
        )
    return assets


def replace_media_with_anchors(xml: str, assets: list[dict[str, Any]]) -> str:
    index = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal index
        tag_name = match.group(1).split(":")[-1].lower()
        if tag_name not in MEDIA_TAGS:
            return match.group(0)
        if index >= len(assets):
            return match.group(0)
        anchor = assets[index]["anchor"]
        index += 1
        return f"<p>[{anchor}]</p>"

    return re.sub(r"<\s*([A-Za-z][\w:.-]*)\b[^>]*?/?>", replace, xml, flags=re.S)


def analyze_blocks(xml: str) -> dict[str, Any]:
    tag_counts = count_tags(xml)
    risky: list[dict[str, Any]] = []
    for tag, meta in RISKY_BLOCKS.items():
        count = tag_counts.get(tag, 0)
        if count:
            risky.append({"tag": tag, "count": count, **meta})

    unknown = [
        {"tag": tag, "count": count}
        for tag, count in tag_counts.items()
        if tag not in KNOWN_STRUCTURE_TAGS and tag not in RISKY_BLOCKS
    ]
    return {
        "tag_counts": tag_counts,
        "risky_blocks": risky,
        "unknown_tags": unknown,
        "media_assets": collect_media_assets(xml),
    }


def placeholder_for_block(tag: str) -> str:
    reason = RISKY_BLOCKS.get(tag, {}).get("reason", "该资源块暂未支持自动重建。")
    return f"<p>[未自动复刻：{tag} 资源块。{reason}]</p>"


def degrade_unsupported_blocks(xml: str) -> tuple[str, list[str]]:
    degraded: list[str] = []
    for tag in RISKY_BLOCKS:
        paired = re.compile(rf"<{tag}\b[^>]*>.*?</{tag}>", flags=re.S | re.I)
        self_closing = re.compile(rf"<{tag}\b[^>]*/>", flags=re.S | re.I)
        xml, paired_count = paired.subn(placeholder_for_block(tag), xml)
        xml, self_count = self_closing.subn(placeholder_for_block(tag), xml)
        count = paired_count + self_count
        if count:
            degraded.append(f"已将 {count} 个 <{tag}> 资源块降级为文本占位。")
    return xml, degraded


def download_media_assets(
    assets: list[dict[str, Any]],
    output_dir: Path,
    profile: str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    media_dir = output_dir / "media"
    media_dir.mkdir(exist_ok=True)
    for asset in assets:
        token = asset.get("token")
        if not token:
            continue
        safe_name = slugify(str(asset.get("name") or asset.get("tag") or asset["type"]))
        output = media_dir / f"{asset['index']:03d}-{safe_name}"
        args = [
            "docs",
            "+media-download",
            "--token",
            str(token),
            "--type",
            "media",
            "--output",
            str(output),
            "--overwrite",
            "--json",
        ]
        if dry_run:
            args.append("--dry-run")
        result = run_lark(args, profile=profile, check=False)
        asset["download_command"] = result["cmd"]
        asset["download_returncode"] = result["returncode"]
        if result["returncode"] == 0:
            payload = result.get("json")
            saved_path = None
            if isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, dict):
                    saved_path = data.get("path") or data.get("output") or data.get("file")
                saved_path = saved_path or payload.get("path") or payload.get("output") or payload.get("file_path")
            asset["downloaded"] = True
            asset["download_path"] = str(saved_path or output)
            asset["status"] = "downloaded" if not dry_run else "download-dry-run"
        else:
            asset["status"] = "download-failed"
            asset["download_error"] = result["stderr"] or result["stdout"]
    return assets


def extract_inspect_info(inspect_payload: dict[str, Any]) -> dict[str, Any]:
    data = first_dict(inspect_payload.get("data"), inspect_payload)
    document = first_dict(data.get("document"))
    return {
        "title": data.get("title") or data.get("name") or document.get("title") or document.get("name"),
        "token": data.get("token") or data.get("obj_token") or data.get("file_token") or document.get("token"),
        "type": data.get("type") or data.get("obj_type") or data.get("file_type") or document.get("type"),
        "url": data.get("url") or document.get("url"),
        "node_token": data.get("node_token") or data.get("wiki_token"),
        "space_id": data.get("space_id"),
    }


def extract_created_file(payload: Any) -> dict[str, Any]:
    data = first_dict(payload.get("data") if isinstance(payload, dict) else None, payload)
    file_obj = first_dict(data.get("file"), data.get("document"), data.get("node"))
    return {
        "token": file_obj.get("token") or file_obj.get("document_id") or file_obj.get("obj_token"),
        "type": file_obj.get("type") or file_obj.get("obj_type"),
        "title": file_obj.get("name") or file_obj.get("title"),
        "url": file_obj.get("url"),
        "raw": payload,
    }


def try_drive_copy(
    source: str,
    title: str,
    inspect_payload: dict[str, Any],
    parent_target: dict[str, str],
    profile: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    info = extract_inspect_info(inspect_payload)
    source_token = info.get("token")
    source_type = info.get("type")
    if not source_token or source_type not in COPYABLE_TYPES:
        return {
            "ok": False,
            "skipped": True,
            "reason": f"Drive copy 需要可复制的 token/type，当前 token={source_token}, type={source_type}",
        }
    if parent_target["type"] != "parent-token":
        return {
            "ok": False,
            "skipped": True,
            "reason": "Drive copy 需要目标 folder token；当前目标不是 parent-token，已回退 rebuild。",
        }

    data = {
        "folder_token": parent_target["value"],
        "name": title,
        "type": source_type,
    }
    cmd = [
        "drive",
        "files",
        "copy",
        "--as",
        "user",
        "--file-token",
        str(source_token),
        "--data",
        json.dumps(data, ensure_ascii=False),
        "--json",
    ]
    if dry_run:
        cmd.append("--dry-run")
    result = run_lark(cmd, profile=profile, check=False)
    payload = result.get("json")
    created = extract_created_file(payload) if isinstance(payload, dict) else {}
    return {
        "ok": result["returncode"] == 0 and (bool(created.get("url")) or dry_run),
        "skipped": False,
        "source": source,
        "cmd": result["cmd"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "payload": payload,
        "url": created.get("url"),
        "token": created.get("token"),
        "type": created.get("type"),
    }


def insert_downloaded_media(
    doc_url: str,
    assets: list[dict[str, Any]],
    profile: str | None = None,
    dry_run: bool = False,
    cleanup_anchor: bool = True,
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for asset in assets:
        path = asset.get("download_path")
        anchor = asset.get("anchor")
        if not path or not anchor or not asset.get("downloaded"):
            asset["insert_status"] = "skipped"
            continue
        media_type = "image" if asset.get("type") == "image" else "file"
        insert_args = [
            "docs",
            "+media-insert",
            "--as",
            "user",
            "--doc",
            doc_url,
            "--file",
            str(path),
            "--type",
            media_type,
            "--selection-with-ellipsis",
            f"[{anchor}]",
            "--json",
        ]
        if media_type == "file":
            insert_args.extend(["--file-view", "card"])
        if dry_run:
            insert_args.append("--dry-run")
        insert_result = run_lark(insert_args, profile=profile, check=False)
        op = {
            "anchor": anchor,
            "file": path,
            "type": media_type,
            "insert_cmd": insert_result["cmd"],
            "insert_returncode": insert_result["returncode"],
            "insert_stdout": insert_result["stdout"],
            "insert_stderr": insert_result["stderr"],
            "insert_payload": insert_result.get("json"),
        }
        asset["insert_status"] = "inserted" if insert_result["returncode"] == 0 else "insert-failed"
        if cleanup_anchor and insert_result["returncode"] == 0:
            cleanup_args = [
                "docs",
                "+update",
                "--as",
                "user",
                "--doc",
                doc_url,
                "--command",
                "str_replace",
                "--pattern",
                f"[{anchor}]",
                "--content",
                "",
                "--json",
            ]
            if dry_run:
                cleanup_args.append("--dry-run")
            cleanup_result = run_lark(cleanup_args, profile=profile, check=False)
            op["cleanup_cmd"] = cleanup_result["cmd"]
            op["cleanup_returncode"] = cleanup_result["returncode"]
            op["cleanup_stdout"] = cleanup_result["stdout"]
            op["cleanup_stderr"] = cleanup_result["stderr"]
            op["cleanup_payload"] = cleanup_result.get("json")
            asset["anchor_cleanup_status"] = "removed" if cleanup_result["returncode"] == 0 else "cleanup-failed"
        operations.append(op)
    return operations


def extract_wiki_node(payload: Any) -> dict[str, Any]:
    data = first_dict(payload.get("data") if isinstance(payload, dict) else None, payload)
    node = first_dict(data.get("node"), data.get("item"), data)
    return {
        "node_token": node.get("node_token") or node.get("token"),
        "space_id": node.get("space_id"),
        "obj_token": node.get("obj_token"),
        "obj_type": node.get("obj_type"),
        "title": node.get("title") or node.get("name"),
        "url": node.get("url"),
        "raw": payload,
    }


def extract_wiki_items(payload: Any) -> list[dict[str, Any]]:
    data = first_dict(payload.get("data") if isinstance(payload, dict) else None, payload)
    items = data.get("items") or data.get("nodes") or data.get("list") or []
    if not isinstance(items, list):
        return []
    return [extract_wiki_node({"data": {"node": item}}) for item in items if isinstance(item, dict)]


def try_wiki_native_copy(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    get_result = run_lark(["wiki", "+node-get", "--as", "user", "--node-token", args.doc, "--json"], profile=args.profile)
    get_payload = get_result.get("json")
    write_json(output_dir / "wiki-source-node.json", get_payload or {"stdout": get_result["stdout"], "stderr": get_result["stderr"]})
    source_node = extract_wiki_node(get_payload)
    if not source_node.get("node_token"):
        raise CloneError("无法解析源 Wiki node_token。")
    if not source_node.get("space_id"):
        raise CloneError("无法解析源 Wiki space_id。")
    copy_cmd = [
        "wiki",
        "+node-copy",
        "--as",
        "user",
        "--node-token",
        str(source_node["node_token"]),
        "--space-id",
        str(source_node["space_id"]),
        "--json",
    ]
    if args.wiki_target_parent_node_token:
        copy_cmd.extend(["--target-parent-node-token", args.wiki_target_parent_node_token])
    else:
        copy_cmd.extend(["--target-space-id", args.wiki_target_space_id or "my_library"])
    if args.title:
        copy_cmd.extend(["--title", args.title])
    if args.yes:
        copy_cmd.append("--yes")
    if args.dry_run:
        copy_cmd.append("--dry-run")
    result = run_lark(copy_cmd, profile=args.profile, check=False)
    payload = result.get("json")
    write_json(output_dir / "wiki-native-copy.json", payload or {"stdout": result["stdout"], "stderr": result["stderr"]})
    copied = extract_wiki_node(payload) if isinstance(payload, dict) else {}
    return {
        "ok": result["returncode"] == 0 and (bool(copied.get("url") or copied.get("node_token")) or args.dry_run),
        "mode": "wiki-native-copy",
        "source": args.doc,
        "source_node": source_node,
        "target_node": copied,
        "cmd": result["cmd"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "payload": payload,
        "output_dir": str(output_dir),
    }


def create_wiki_doc_node(
    title: str,
    args: argparse.Namespace,
    parent_node_token: str | None = None,
) -> dict[str, Any]:
    cmd = [
        "wiki",
        "+node-create",
        "--as",
        "user",
        "--obj-type",
        "docx",
        "--title",
        title,
        "--json",
    ]
    if parent_node_token:
        cmd.extend(["--parent-node-token", parent_node_token])
    else:
        cmd.extend(["--space-id", args.wiki_target_space_id or "my_library"])
    if args.dry_run:
        cmd.append("--dry-run")
    result = run_lark(cmd, profile=args.profile, check=False)
    payload = result.get("json")
    node = extract_wiki_node(payload) if isinstance(payload, dict) else {}
    node.update({"cmd": result["cmd"], "returncode": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"]})
    if result["returncode"] != 0:
        raise CloneError(result["stderr"] or result["stdout"] or "wiki +node-create failed")
    return node


def fetch_normalized_content_for_doc(doc: str, args: argparse.Namespace, output_dir: Path) -> tuple[str, str, list[str], dict[str, Any]]:
    inspect = run_lark(["drive", "+inspect", "--url", doc, "--json"], profile=args.profile, check=False)
    write_json(output_dir / "inspect.json", inspect.get("json") or {"stdout": inspect["stdout"], "stderr": inspect["stderr"]})
    fetch = run_lark(
        [
            "docs",
            "+fetch",
            "--doc",
            doc,
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
    clone_xml, warnings, diagnostics = normalize_xml(
        raw_xml,
        degrade_unsupported=args.degrade_unsupported,
        reinsert_media=False,
    )
    (output_dir / "content.clone.xml").write_text(clone_xml, encoding="utf-8")
    write_json(output_dir / "block-report.json", diagnostics)
    title = args.title or extract_title(inspect.get("json") or {}, document, args.title_suffix)
    return title, clone_xml, warnings, diagnostics


def overwrite_wiki_node_content(target_node: dict[str, Any], content_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    doc_target = target_node.get("url") or target_node.get("obj_token") or target_node.get("node_token")
    if not doc_target:
        raise CloneError("新 Wiki 节点没有可写入的 doc token/url。")
    cmd = [
        "docs",
        "+update",
        "--as",
        "user",
        "--doc",
        str(doc_target),
        "--command",
        "overwrite",
        "--content",
        f"@{content_path.name}",
        "--json",
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    result = run_lark(cmd, profile=args.profile, cwd=content_path.parent, check=False)
    return {
        "ok": result["returncode"] == 0,
        "cmd": result["cmd"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "payload": result.get("json"),
    }


def clone_wiki_subtree(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = make_output_dir(args.doc + "-wiki-tree")
    env = check_environment(args.profile)
    ok, reason = has_usable_profile(env)
    if not ok and not args.allow_stale_token:
        raise CloneError(reason)
    write_json(output_dir / "environment.json", summarize_environment(env))

    if args.wiki_native_copy:
        if not args.yes and not args.dry_run:
            raise CloneError("wiki +node-copy 是高风险写操作。请确认后添加 --yes，或改用默认递归重建。")
        result = try_wiki_native_copy(args, output_dir)
        write_json(output_dir / "result.json", result)
        if not result.get("ok"):
            raise CloneError(result.get("stderr") or result.get("stdout") or "Wiki 原生复制失败。")
        return result

    source_get = run_lark(["wiki", "+node-get", "--as", "user", "--node-token", args.doc, "--json"], profile=args.profile)
    source_payload = source_get.get("json")
    source_node = extract_wiki_node(source_payload)
    write_json(output_dir / "wiki-source-node.json", source_payload or {"stdout": source_get["stdout"], "stderr": source_get["stderr"]})
    if not source_node.get("node_token") or not source_node.get("space_id"):
        raise CloneError("无法解析源 Wiki node_token/space_id。")

    results: list[dict[str, Any]] = []

    def recurse(node: dict[str, Any], parent_target: str | None, depth: int) -> dict[str, Any]:
        if depth > args.wiki_max_depth:
            return {"ok": False, "source_node": node, "skipped": True, "reason": "超过 --wiki-max-depth"}
        node_dir = output_dir / f"{len(results) + 1:03d}-{slugify(str(node.get('title') or node.get('node_token')))}"
        node_dir.mkdir(parents=True, exist_ok=True)
        source_doc = node.get("url") or node.get("obj_token") or node.get("node_token")
        title, _clone_xml, warnings, diagnostics = fetch_normalized_content_for_doc(str(source_doc), args, node_dir)
        target_node = create_wiki_doc_node(title, args, parent_target)
        update = overwrite_wiki_node_content(target_node, node_dir / "content.clone.xml", args)
        item_result = {
            "ok": update.get("ok"),
            "source_node": node,
            "target_node": target_node,
            "output_dir": str(node_dir),
            "warnings": warnings,
            "block_report": diagnostics,
            "update": update,
        }
        results.append(item_result)

        if depth < args.wiki_max_depth:
            children_result = run_lark(
                [
                    "wiki",
                    "+node-list",
                    "--as",
                    "user",
                    "--space-id",
                    str(node["space_id"]),
                    "--parent-node-token",
                    str(node["node_token"]),
                    "--page-all",
                    "--json",
                ],
                profile=args.profile,
                check=False,
            )
            write_json(node_dir / "children.json", children_result.get("json") or {"stdout": children_result["stdout"], "stderr": children_result["stderr"]})
            if children_result["returncode"] == 0:
                for child in extract_wiki_items(children_result.get("json")):
                    child["space_id"] = child.get("space_id") or node.get("space_id")
                    recurse(child, target_node.get("node_token"), depth + 1)
        return item_result

    root = recurse(source_node, args.wiki_target_parent_node_token, 0)
    summary = {
        "ok": all(item.get("ok") for item in results),
        "mode": "wiki-recursive-rebuild",
        "source": args.doc,
        "root": root,
        "count": len(results),
        "output_dir": str(output_dir),
        "results": results,
    }
    write_json(output_dir / "result.json", summary)
    return summary


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CloneError(f"配置文件读取失败：{CONFIG_PATH} ({exc})")
    if not isinstance(payload, dict):
        raise CloneError(f"配置文件必须是 JSON object：{CONFIG_PATH}")
    return payload


def resolve_parent_target(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, str]:
    cli_token = (args.parent_token or "").strip()
    cli_position = (args.parent_position or "").strip()
    env_token = (os.environ.get("LARK_DOC_CLONER_PARENT_TOKEN") or "").strip()
    env_position = (os.environ.get("LARK_DOC_CLONER_PARENT_POSITION") or "").strip()
    config_token = str(config.get("parent_token") or "").strip()
    config_position = str(config.get("parent_position") or "").strip()

    if cli_token:
        return {"type": "parent-token", "value": cli_token, "source": "cli"}
    if cli_position:
        return {"type": "parent-position", "value": cli_position, "source": "cli"}
    if env_token:
        return {"type": "parent-token", "value": env_token, "source": "env:LARK_DOC_CLONER_PARENT_TOKEN"}
    if config_token:
        return {"type": "parent-token", "value": config_token, "source": str(CONFIG_PATH)}
    if env_position:
        return {"type": "parent-position", "value": env_position, "source": "env:LARK_DOC_CLONER_PARENT_POSITION"}
    if config_position:
        return {"type": "parent-position", "value": config_position, "source": str(CONFIG_PATH)}
    return {"type": "drive-root", "value": DEFAULT_PARENT_TARGET, "source": "default"}


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


def normalize_xml(
    content: str,
    degrade_unsupported: bool = False,
    reinsert_media: bool = False,
) -> tuple[str, list[str], dict[str, Any]]:
    warnings: list[str] = []
    xml = content.strip()
    diagnostics = analyze_blocks(xml)

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

    for item in diagnostics["risky_blocks"]:
        warnings.append(f"检测到 {item['count']} 个 <{item['tag']}> 资源块：{item['reason']}")
    if diagnostics["unknown_tags"]:
        unknown_text = ", ".join(f"<{item['tag']}>×{item['count']}" for item in diagnostics["unknown_tags"][:20])
        warnings.append(f"检测到未登记标签：{unknown_text}。请人工检查保真度。")

    if reinsert_media and diagnostics["media_assets"]:
        xml = replace_media_with_anchors(xml, diagnostics["media_assets"])
        warnings.append("已将媒体块替换为锚点，创建后会尝试把下载的图片/附件插回锚点位置。")

    if degrade_unsupported:
        xml, degraded_warnings = degrade_unsupported_blocks(xml)
        warnings.extend(degraded_warnings)

    if "<title" not in xml.lower():
        warnings.append("原始 XML 没有 <title>，将使用 inspect 或默认标题创建。")
    else:
        # The script passes --title to docs +create, so keeping <title> in the
        # body would make lark-cli filter a duplicate title. Remove it here and
        # keep the effective title in the command argument.
        xml = re.sub(r"<title\b[^>]*>.*?</title>", "", xml, flags=re.S | re.I).strip()

    diagnostics["warnings"] = warnings
    return xml + "\n", warnings, diagnostics


def clone_doc(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config()
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
    parent_target = resolve_parent_target(args, config)

    inspect = run_lark(["drive", "+inspect", "--url", args.doc, "--json"], profile=args.profile)
    write_json(output_dir / "inspect.json", inspect.get("json") or {"stdout": inspect["stdout"], "stderr": inspect["stderr"]})
    inspect_payload = inspect.get("json") if isinstance(inspect.get("json"), dict) else {}
    pre_title = args.title or extract_title(inspect_payload, {"content": ""}, args.title_suffix)

    if args.mode in {"auto", "copy"}:
        copy_result = try_drive_copy(
            args.doc,
            pre_title,
            inspect_payload,
            parent_target,
            profile=args.profile,
            dry_run=args.dry_run,
        )
        write_json(output_dir / "copy.json", copy_result)
        if copy_result.get("ok"):
            result = {
                "ok": True,
                "mode": "copy",
                "source": args.doc,
                "title": pre_title,
                "url": copy_result.get("url"),
                "target": parent_target,
                "output_dir": str(output_dir),
                "copy": copy_result,
                "warnings": [],
            }
            write_json(output_dir / "result.json", result)
            return result
        if args.mode == "copy":
            raise CloneError(f"Drive copy 失败：{copy_result.get('reason') or copy_result.get('stderr') or copy_result.get('stdout')}")

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

    clone_xml, warnings, diagnostics = normalize_xml(
        raw_xml,
        degrade_unsupported=args.degrade_unsupported,
        reinsert_media=args.reinsert_media,
    )
    content_path = output_dir / "content.clone.xml"
    content_path.write_text(clone_xml, encoding="utf-8")
    write_json(output_dir / "block-report.json", diagnostics)

    media_assets = diagnostics.get("media_assets", [])
    if (args.download_media or args.reinsert_media) and isinstance(media_assets, list):
        media_assets = download_media_assets(media_assets, output_dir, profile=args.profile, dry_run=args.dry_run)
        diagnostics["media_assets"] = media_assets
        write_json(output_dir / "block-report.json", diagnostics)
    write_json(output_dir / "media-manifest.json", media_assets)

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
            "block_report_path": str(output_dir / "block-report.json"),
            "media_manifest_path": str(output_dir / "media-manifest.json"),
            "block_report": diagnostics,
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
    if parent_target["type"] == "parent-token":
        create_cmd.extend(["--parent-token", parent_target["value"]])
    elif parent_target["type"] == "parent-position":
        create_cmd.extend(["--parent-position", parent_target["value"]])

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

    media_insert_operations: list[dict[str, Any]] = []
    if args.reinsert_media and new_url:
        media_insert_operations = insert_downloaded_media(
            new_url,
            media_assets if isinstance(media_assets, list) else [],
            profile=args.profile,
            dry_run=args.dry_run,
            cleanup_anchor=not args.keep_media_anchors,
        )
        write_json(output_dir / "media-insert.json", media_insert_operations)
        diagnostics["media_assets"] = media_assets
        write_json(output_dir / "block-report.json", diagnostics)
        write_json(output_dir / "media-manifest.json", media_assets)

    result = {
        "ok": bool(new_url) or args.dry_run,
        "mode": "rebuild",
        "source": args.doc,
        "title": title,
        "url": new_url,
        "target": parent_target,
        "output_dir": str(output_dir),
        "content_path": str(content_path),
        "block_report_path": str(output_dir / "block-report.json"),
        "media_manifest_path": str(output_dir / "media-manifest.json"),
        "block_report": diagnostics,
        "media_insert_path": str(output_dir / "media-insert.json") if args.reinsert_media else None,
        "media_insert_operations": media_insert_operations,
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
    parser.add_argument("doc_arg", nargs="?", help="Optional positional Lark/Feishu document URL or token.")
    parser.add_argument("--doc", help="Lark/Feishu document URL or token.")
    parser.add_argument("--docs-file", help="Text file containing one Lark/Feishu document URL per line for batch cloning.")
    parser.add_argument("--profile", help="lark-cli profile name. Defaults to active profile.")
    parser.add_argument("--parent-position", help="Target position, e.g. my_library. Defaults to Drive root.")
    parser.add_argument("--parent-token", help="Target folder token or wiki parent node token.")
    parser.add_argument("--title", help="Override new document title.")
    parser.add_argument("--title-suffix", default=" - clone", help="Suffix appended to source title.")
    parser.add_argument("--mode", choices=["auto", "copy", "rebuild"], default="auto", help="Clone strategy: try Drive copy first, force copy, or force rebuild.")
    parser.add_argument("--download-media", action="store_true", help="Download media/file tokens found in XML into the output media directory.")
    parser.add_argument("--reinsert-media", action="store_true", help="Replace media tags with anchors, then insert downloaded images/files back near those anchors after document creation.")
    parser.add_argument("--keep-media-anchors", action="store_true", help="Keep media anchor text after --reinsert-media instead of deleting it.")
    parser.add_argument("--degrade-unsupported", action="store_true", help="Replace known unsupported resource blocks with text placeholders.")
    parser.add_argument("--wiki-recursive", action="store_true", help="Recursively clone a Wiki node tree by rebuilding each docx node.")
    parser.add_argument("--wiki-native-copy", action="store_true", help="Use lark-cli wiki +node-copy instead of rebuild recursion. Requires --yes unless --dry-run.")
    parser.add_argument("--wiki-target-space-id", help="Target Wiki space ID for recursive or native Wiki copy. Defaults to my_library.")
    parser.add_argument("--wiki-target-parent-node-token", help="Target parent Wiki node token for recursive or native Wiki copy.")
    parser.add_argument("--wiki-max-depth", type=int, default=20, help="Maximum depth for --wiki-recursive rebuild.")
    parser.add_argument("--yes", action="store_true", help="Confirm high-risk operations such as native Wiki node copy.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue batch cloning after a document fails.")
    parser.add_argument("--fetch-only", action="store_true", help="Fetch and normalize only; do not create a new document.")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to the create call.")
    parser.add_argument("--check", action="store_true", help="Only check lark-cli and profile status.")
    parser.add_argument("--install-help", action="store_true", help="Print lark-cli installation guidance.")
    parser.add_argument("--allow-stale-token", action="store_true", help="Continue even if profile tokenStatus is not ok.")
    return parser


def read_docs_file(path: str) -> list[str]:
    docs: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        value = line.strip().lstrip("\ufeff")
        if not value or value.startswith("#"):
            continue
        docs.append(value)
    return docs


def clone_batch(args: argparse.Namespace) -> dict[str, Any]:
    docs = read_docs_file(args.docs_file)
    if not docs:
        raise CloneError(f"批量文件里没有可用链接：{args.docs_file}")
    batch_dir = OUTPUT_ROOT / f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-batch"
    batch_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for index, doc in enumerate(docs, start=1):
        item_args = argparse.Namespace(**vars(args))
        item_args.doc = doc
        item_args.docs_file = None
        try:
            result = clone_doc(item_args)
            result["batch_index"] = index
            results.append(result)
        except CloneError as exc:
            failure = {"ok": False, "batch_index": index, "source": doc, "error": str(exc)}
            results.append(failure)
            if not args.continue_on_error:
                write_json(batch_dir / "batch-result.json", {"ok": False, "results": results})
                raise
    ok = all(item.get("ok") for item in results)
    summary = {
        "ok": ok,
        "mode": "batch",
        "count": len(results),
        "success_count": sum(1 for item in results if item.get("ok")),
        "failure_count": sum(1 for item in results if not item.get("ok")),
        "output_dir": str(batch_dir),
        "results": results,
    }
    write_json(batch_dir / "batch-result.json", summary)
    return summary


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.doc and args.doc_arg:
        args.doc = args.doc_arg
    if args.install_help:
        print(install_help_text())
        return 0
    try:
        if args.docs_file:
            result = clone_batch(args)
        elif args.wiki_recursive or args.wiki_native_copy:
            result = clone_wiki_subtree(args)
        else:
            result = clone_doc(args)
    except CloneError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
