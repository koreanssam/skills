#!/usr/bin/env python3
"""Enforce immediate, literal, page-by-page visual transcription."""

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


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def neutral(event: str) -> int:
    if event == "pre-tool":
        return emit({"decision": "allow"})
    if event == "pre-invocation":
        return emit({"injectSteps": []})
    if event == "stop":
        return emit({"decision": "allow"})
    return emit({})


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
    return next((page for page in manifest["pages"] if not page.get("viewed")), None)


def pending_transcription(manifest: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            page
            for page in manifest["pages"]
            if page.get("viewed") and not page.get("transcribed")
        ),
        None,
    )


def page_by_number(manifest: dict[str, Any], number: int) -> dict[str, Any]:
    return next(page for page in manifest["pages"] if page["number"] == number)


def compose_output(manifest: dict[str, Any]) -> str:
    sections = ["# 전사문"]
    for page in manifest["pages"]:
        if not page.get("transcribed"):
            break
        draft = Path(page["draftPath"]).read_text(encoding="utf-8").rstrip("\n")
        sections.append(f"## Page {page['number']}\n\n{draft}")
    return "\n\n".join(sections) + "\n"


def validate_draft(page: dict[str, Any]) -> str | None:
    draft = Path(page["draftPath"])
    if not draft.is_file():
        return f"Page draft was not created: {draft}"
    try:
        content = draft.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Page draft must be UTF-8 text: {draft}"
    stripped = content.strip()
    if not stripped:
        return "Page draft is empty. Use [빈 페이지] only after visually confirming a blank page."
    if re.search(r"(?m)^## Page \d+\s*$", content):
        return "Write only the literal page text; the hook adds page headings automatically."
    return None


def pre_tool(path: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> int:
    name = tool_name(payload)
    args = tool_args(payload)
    pending = pending_transcription(manifest)

    if name == "view_file":
        if manifest.get("pendingViews"):
            return emit(
                {
                    "decision": "deny",
                    "reason": "Wait for the current view_file result before another tool call.",
                }
            )
        page = pending or next_page(manifest)
        if page is None:
            return emit(
                {"decision": "deny", "reason": "Every page is already transcribed."}
            )
        requested = first_arg(args, "AbsolutePath", "path", "filePath")
        expected = Path(page["imagePath"]).resolve()
        if not requested or Path(requested).expanduser().resolve() != expected:
            action = (
                "Re-open the current page"
                if pending
                else f"View page {page['number']} next"
            )
            return emit(
                {"decision": "deny", "reason": f"{action} with view_file: {expected}"}
            )
        if not expected.is_file() or digest(expected) != page["imageSha256"]:
            return emit(
                {
                    "decision": "deny",
                    "reason": "Rendered page identity changed. Start a new transcription session.",
                }
            )
        if payload.get("stepIdx") is None:
            return emit(
                {"decision": "deny", "reason": "Missing hook stepIdx for page view."}
            )
        manifest.setdefault("pendingViews", {})[str(payload["stepIdx"])] = page[
            "number"
        ]
        save_json(path, manifest)
        return emit({"decision": "allow"})

    if name in WRITE_TOOLS:
        if pending is None:
            page = next_page(manifest)
            reason = (
                f"View page {page['number']} before writing its draft."
                if page
                else "Every page is already transcribed; the output was assembled automatically."
            )
            return emit({"decision": "deny", "reason": reason})
        if name != "write_to_file":
            return emit(
                {
                    "decision": "deny",
                    "reason": "Use write_to_file for the current page draft; do not edit prior pages.",
                }
            )
        if manifest.get("pendingDrafts"):
            return emit(
                {
                    "decision": "deny",
                    "reason": "Wait for the current page-draft write result.",
                }
            )
        target = first_arg(args, "TargetFile", "AbsolutePath", "path", "filePath")
        expected = Path(pending["draftPath"]).resolve()
        if not target or Path(target).expanduser().resolve() != expected:
            return emit(
                {
                    "decision": "deny",
                    "reason": (
                        f"Immediately write only what is visibly present on page {pending['number']} "
                        f"to {expected}. Preserve bullets, arrows, corrections, and line breaks."
                    ),
                }
            )
        if payload.get("stepIdx") is None:
            return emit(
                {"decision": "deny", "reason": "Missing hook stepIdx for draft write."}
            )
        manifest.setdefault("pendingDrafts", {})[str(payload["stepIdx"])] = pending[
            "number"
        ]
        save_json(path, manifest)
        return emit({"decision": "allow"})

    reason = (
        f"Page {pending['number']} must be transcribed immediately to {pending['draftPath']}."
        if pending
        else "Only the required page view_file call is allowed now."
    )
    return emit({"decision": "deny", "reason": reason})


def post_tool(path: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> int:
    step_key = str(payload.get("stepIdx"))
    page_number = manifest.setdefault("pendingViews", {}).pop(step_key, None)
    if page_number is not None and not payload.get("error"):
        page = page_by_number(manifest, int(page_number))
        page["viewed"] = True
        page["viewedStepIdx"] = payload.get("stepIdx")
        page["viewedAt"] = datetime.now(timezone.utc).isoformat()

    draft_number = manifest.setdefault("pendingDrafts", {}).pop(step_key, None)
    if draft_number is not None and not payload.get("error"):
        page = page_by_number(manifest, int(draft_number))
        error = validate_draft(page)
        if error:
            page["draftError"] = error
        else:
            page.pop("draftError", None)
            page["draftSha256"] = digest(Path(page["draftPath"]))
            page["transcribed"] = True
            page["transcribedStepIdx"] = payload.get("stepIdx")
            page["transcribedAt"] = datetime.now(timezone.utc).isoformat()
            write_text_atomic(Path(manifest["outputPath"]), compose_output(manifest))
    save_json(path, manifest)
    return emit({})


def pre_invocation(manifest: dict[str, Any]) -> int:
    pending = pending_transcription(manifest)
    if pending:
        prior_error = pending.get("draftError")
        message = (
            f"Page {pending['number']} of {manifest['pageCount']} was just viewed. Before any "
            f"other page, use write_to_file on {pending['draftPath']}. Transcribe only visible "
            "marks in top-to-bottom order. Preserve each bullet, arrow, line break, misspelling, "
            "and correction. Do not summarize, polish, complete, explain, or infer. Use "
            "[판독 불가] for any unreadable span. Re-open this same image with view_file if needed."
        )
        if prior_error:
            message += f" Previous draft was rejected: {prior_error}"
    else:
        page = next_page(manifest)
        if page:
            message = (
                f"View page {page['number']} of {manifest['pageCount']} now with view_file: "
                f"{page['imagePath']}. Inspect the actual pixels; do not recall or predict text."
            )
        else:
            message = "Every page was viewed and immediately transcribed. The output is complete."
    return emit({"injectSteps": [{"ephemeralMessage": message}]})


def stop(path: Path, manifest: dict[str, Any]) -> int:
    pending = pending_transcription(manifest)
    if pending:
        return emit(
            {
                "decision": "continue",
                "reason": (
                    f"Cannot finish: transcribe the just-viewed page {pending['number']} to "
                    f"{pending['draftPath']} before proceeding."
                ),
            }
        )
    page = next_page(manifest)
    if page:
        return emit(
            {
                "decision": "continue",
                "reason": f"Cannot finish: page {page['number']} still needs view_file inspection.",
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
    for page in manifest["pages"]:
        image_path = Path(page["imagePath"])
        if not image_path.is_file() or digest(image_path) != page["imageSha256"]:
            return emit(
                {
                    "decision": "continue",
                    "reason": f"Rendered image for page {page['number']} changed unexpectedly.",
                }
            )
        draft = Path(page["draftPath"])
        if not draft.is_file() or digest(draft) != page.get("draftSha256"):
            return emit(
                {
                    "decision": "continue",
                    "reason": f"Completed page {page['number']} draft was changed unexpectedly.",
                }
            )
    expected_output = compose_output(manifest)
    output = Path(manifest["outputPath"])
    try:
        actual_output = output.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        actual_output = ""
    if actual_output != expected_output:
        write_text_atomic(output, expected_output)
        return emit(
            {
                "decision": "continue",
                "reason": "The hook restored the literal output from immutable page drafts.",
            }
        )
    manifest["active"] = False
    manifest["completedAt"] = datetime.now(timezone.utc).isoformat()
    save_json(path, manifest)
    return emit({"decision": "allow"})


def main() -> int:
    events = {"pre-tool", "post-tool", "pre-invocation", "stop"}
    if len(sys.argv) != 2 or sys.argv[1] not in events:
        raise SystemExit(
            "Usage: transcription_hook.py pre-tool|post-tool|pre-invocation|stop"
        )
    event = sys.argv[1]
    payload = load_input()
    path, manifest = manifest_for(payload)
    if path is None or manifest is None:
        return neutral(event)
    if manifest.get("version") != 2:
        return neutral(event)

    claimed = manifest.get("conversationId")
    current = payload.get("conversationId")
    if not claimed and current:
        manifest["conversationId"] = current
        save_json(path, manifest)
    elif claimed and current and claimed != current:
        return neutral(event)

    if event == "pre-tool":
        return pre_tool(path, manifest, payload)
    if event == "post-tool":
        return post_tool(path, manifest, payload)
    if event == "pre-invocation":
        return pre_invocation(manifest)
    return stop(path, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
