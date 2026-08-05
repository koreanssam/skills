#!/usr/bin/env python3
"""Antigravity lifecycle hook enforcing direct view_file coverage for every PDF page."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_RELATIVE = Path(".transcription/session.json")
WRITE_TOOLS = {"write_to_file", "replace_file_content", "multi_replace_file_content"}


def emit(value: dict[str, Any]) -> int:
    json.dump(value, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_input() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        raise SystemExit(f"Invalid hook input: {error}")
    if not isinstance(value, dict):
        raise SystemExit("Hook input must be a JSON object")
    return value


def manifest_for(payload: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    for workspace_value in payload.get("workspacePaths") or []:
        path = Path(workspace_value).resolve() / STATE_RELATIVE
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("active"):
                return path, value
    return None, None


def save(path: Path, value: dict[str, Any]) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def claim_conversation(
    path: Path, manifest: dict[str, Any], payload: dict[str, Any]
) -> str | None:
    conversation_id = payload.get("conversationId")
    claimed = manifest.get("conversationId")
    if claimed and conversation_id and claimed != conversation_id:
        return f"Transcription session belongs to another conversation: {claimed}"
    if conversation_id and not claimed:
        manifest["conversationId"] = conversation_id
        save(path, manifest)
    return None


def tool_name(payload: dict[str, Any]) -> str:
    return str((payload.get("toolCall") or {}).get("name") or "").lower()


def tool_args(payload: dict[str, Any]) -> dict[str, Any]:
    args = (payload.get("toolCall") or {}).get("args") or {}
    return args if isinstance(args, dict) else {}


def first_arg(args: dict[str, Any], *names: str) -> str | None:
    folded = {str(key).lower(): value for key, value in args.items()}
    for name in names:
        value = folded.get(name.lower())
        if isinstance(value, str) and value:
            return value
    return None


def next_page(manifest: dict[str, Any]) -> dict[str, Any] | None:
    return next((page for page in manifest["pages"] if not page["viewed"]), None)


def pre_tool(path: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> int:
    error = claim_conversation(path, manifest, payload)
    if error:
        return emit({"decision": "deny", "reason": error})
    name = tool_name(payload)
    args = tool_args(payload)

    if name == "run_command":
        return emit(
            {
                "decision": "deny",
                "reason": (
                    "Shell commands are disabled during the guarded transcription. "
                    "Use only the required view_file calls, then write the registered output."
                ),
            }
        )

    if name == "view_file":
        page = next_page(manifest)
        if page is None:
            return emit(
                {
                    "decision": "deny",
                    "reason": "All pages are already viewed; write the registered transcript output.",
                }
            )
        requested = first_arg(args, "AbsolutePath", "path", "filePath")
        expected = Path(page["imagePath"]).resolve()
        if not requested or Path(requested).expanduser().resolve() != expected:
            return emit(
                {
                    "decision": "deny",
                    "reason": f"View page {page['number']} next with view_file: {expected}",
                }
            )
        if not expected.is_file() or digest(expected) != page["imageSha256"]:
            return emit(
                {
                    "decision": "deny",
                    "reason": "Rendered page identity changed. Start a new transcription session.",
                }
            )
        step_key = str(payload.get("stepIdx"))
        manifest.setdefault("pendingViews", {})[step_key] = page["number"]
        save(path, manifest)
        return emit({"decision": "allow"})

    if name in WRITE_TOOLS:
        page = next_page(manifest)
        if page is not None:
            return emit(
                {
                    "decision": "deny",
                    "reason": f"Page {page['number']} has not been viewed with view_file yet.",
                }
            )
        target = first_arg(args, "TargetFile", "AbsolutePath", "path", "filePath")
        expected_output = Path(manifest["outputPath"]).resolve()
        if not target or Path(target).expanduser().resolve() != expected_output:
            return emit(
                {
                    "decision": "deny",
                    "reason": f"Write only the registered transcript output: {expected_output}",
                }
            )
        return emit({"decision": "allow"})

    return emit(
        {
            "decision": "deny",
            "reason": (
                f"Tool {name or '(unknown)'} is disabled during guarded transcription. "
                "Only the required view_file calls and the registered output write are allowed."
            ),
        }
    )


def post_tool(path: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> int:
    step_key = str(payload.get("stepIdx"))
    page_number = manifest.setdefault("pendingViews", {}).pop(step_key, None)
    if page_number is not None and not payload.get("error"):
        page = manifest["pages"][int(page_number) - 1]
        page["viewed"] = True
        page["viewedStepIdx"] = payload.get("stepIdx")
        page["viewedAt"] = datetime.now(timezone.utc).isoformat()
    save(path, manifest)
    return emit({})


def pre_invocation(manifest: dict[str, Any]) -> int:
    page = next_page(manifest)
    if page:
        message = (
            f"Guarded transcription: page {page['number']} of {manifest['pageCount']} must be "
            f"visually inspected next. Call view_file with AbsolutePath={page['imagePath']}. "
            "Read only the visible handwriting; never guess or use OCR."
        )
    else:
        message = (
            "Every page has a successful view_file call. Write the faithful transcript now to "
            f"{manifest['outputPath']} with headings ## Page 1 through "
            f"## Page {manifest['pageCount']}."
        )
    return emit({"injectSteps": [{"ephemeralMessage": message}]})


def stop(path: Path, manifest: dict[str, Any]) -> int:
    page = next_page(manifest)
    if page:
        return emit(
            {
                "decision": "continue",
                "reason": (
                    f"Cannot finish: page {page['number']} of {manifest['pageCount']} still needs "
                    f"a successful view_file call for {page['imagePath']}."
                ),
            }
        )
    source = Path(manifest["sourcePdf"])
    if not source.is_file() or digest(source) != manifest["sourceSha256"]:
        return emit(
            {
                "decision": "continue",
                "reason": "The source PDF changed during transcription. Start a new session.",
            }
        )
    output = Path(manifest["outputPath"])
    if not output.is_file() or output.stat().st_size == 0:
        return emit(
            {
                "decision": "continue",
                "reason": f"Cannot finish: write the transcript to {output}.",
            }
        )
    try:
        content = output.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return emit(
            {
                "decision": "continue",
                "reason": f"Cannot finish: transcript output is not valid UTF-8 text: {output}",
            }
        )
    headings = [int(value) for value in re.findall(r"(?m)^## Page (\d+)\s*$", content)]
    expected_headings = list(range(1, manifest["pageCount"] + 1))
    if headings != expected_headings:
        return emit(
            {
                "decision": "continue",
                "reason": (
                    "Cannot finish: page headings must occur exactly once and in order. "
                    f"Expected {expected_headings}; found {headings}."
                ),
            }
        )
    manifest["active"] = False
    manifest["completedAt"] = datetime.now(timezone.utc).isoformat()
    save(path, manifest)
    return emit({"decision": "allow"})


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "pre-tool",
        "post-tool",
        "pre-invocation",
        "stop",
    }:
        raise SystemExit(
            "Usage: transcription_hook.py pre-tool|post-tool|pre-invocation|stop"
        )
    payload = load_input()
    path, manifest = manifest_for(payload)
    if path is None or manifest is None:
        if sys.argv[1] == "pre-tool":
            return emit({"decision": "allow"})
        if sys.argv[1] == "pre-invocation":
            return emit({"injectSteps": []})
        if sys.argv[1] == "stop":
            return emit({"decision": "allow"})
        return emit({})
    claimed = manifest.get("conversationId")
    current = payload.get("conversationId")
    if not claimed and current:
        manifest["conversationId"] = current
        save(path, manifest)
    elif claimed and current and claimed != current:
        if sys.argv[1] == "pre-tool":
            return emit({"decision": "allow"})
        if sys.argv[1] == "pre-invocation":
            return emit({"injectSteps": []})
        if sys.argv[1] == "stop":
            return emit({"decision": "allow"})
        return emit({})
    if sys.argv[1] == "pre-tool":
        return pre_tool(path, manifest, payload)
    if sys.argv[1] == "post-tool":
        return post_tool(path, manifest, payload)
    if sys.argv[1] == "pre-invocation":
        return pre_invocation(manifest)
    return stop(path, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
