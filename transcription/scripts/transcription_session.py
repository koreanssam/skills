#!/usr/bin/env python3
"""Create and inspect a page-verified handwritten-PDF transcription session."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = ".transcription"
MANIFEST_NAME = "session.json"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json_atomic(path: Path, value: dict) -> None:
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


def ensure_pdf(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"PDF not found: {path}")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise SystemExit(f"Not a PDF file: {path}")


def pdf_page_count(pdf: Path) -> int:
    executable = shutil.which("pdfinfo")
    if not executable:
        raise SystemExit("pdfinfo is required to validate PDF page selection")
    process = subprocess.run(
        [executable, str(pdf)], text=True, capture_output=True, check=False
    )
    if process.returncode:
        raise SystemExit(f"pdfinfo failed: {process.stderr.strip()}")
    match = re.search(r"(?m)^Pages:\s+(\d+)\s*$", process.stdout)
    if not match:
        raise SystemExit("Could not determine PDF page count")
    return int(match.group(1))


def parse_pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    selected: set[int] = set()
    for item in spec.split(","):
        item = item.strip()
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", item)
        if not match:
            raise SystemExit(f"Invalid --pages item: {item!r}")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first > last or first < 1 or last > total:
            raise SystemExit(f"Page range outside 1-{total}: {item}")
        selected.update(range(first, last + 1))
    if not selected:
        raise SystemExit("--pages selected no pages")
    return sorted(selected)


def render_pages(
    pdf: Path, page_dir: Path, dpi: int, selected: list[int], total: int
) -> list[Path]:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise SystemExit(
            "pdftoppm is required only to render page images (no OCR/text extraction). "
            "Install Poppler, then retry."
        )
    page_dir.mkdir(parents=True, exist_ok=False)
    if selected == list(range(1, total + 1)):
        commands = [
            [executable, "-png", "-r", str(dpi), str(pdf), str(page_dir / "page")]
        ]
    else:
        commands = [
            [
                executable,
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(number),
                "-l",
                str(number),
                "-singlefile",
                str(pdf),
                str(page_dir / f"page-{number:04d}"),
            ]
            for number in selected
        ]
    for command in commands:
        process = subprocess.run(command, text=True, capture_output=True, check=False)
        if process.returncode:
            raise SystemExit(f"pdftoppm failed: {process.stderr.strip()}")
    pages = sorted(page_dir.glob("page-*.png"), key=page_number)
    if not pages:
        raise SystemExit("PDF rendering produced no pages")
    return pages


def page_number(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    if not match:
        raise ValueError(f"Unexpected rendered page name: {path}")
    return int(match.group(1))


def start(args: argparse.Namespace) -> int:
    workspace = args.workspace.expanduser().resolve()
    pdf = args.pdf.expanduser().resolve()
    output = args.output.expanduser().resolve()
    ensure_pdf(pdf)
    if output == pdf:
        raise SystemExit("Output path must differ from the source PDF")
    if not (72 <= args.dpi <= 600):
        raise SystemExit("--dpi must be between 72 and 600")

    state_root = workspace / STATE_DIR
    state_root.mkdir(parents=True, exist_ok=True)
    manifest_path = state_root / MANIFEST_NAME
    lock_path = state_root / "start.lock"

    # Hold the lock through rendering. A second start waits, then sees the active
    # manifest instead of rendering a competing set of pages.
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if previous.get("active"):
                raise SystemExit(
                    f"An active session already exists for {previous.get('sourcePdf')}. "
                    "Finish it before starting another."
                )

        source_hash = digest(pdf)
        total_pages = pdf_page_count(pdf)
        selected_pages = parse_pages(args.pages, total_pages)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        session_dir = state_root / "sessions" / f"{stamp}-{source_hash[:12]}"
        pages = render_pages(
            pdf, session_dir / "pages", args.dpi, selected_pages, total_pages
        )
        expected = selected_pages
        actual = [page_number(path) for path in pages]
        if actual != expected:
            raise SystemExit(f"Rendered pages are not contiguous: {actual}")
        draft_dir = session_dir / "drafts"
        draft_dir.mkdir()

        manifest = {
            "version": 2,
            "active": True,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "conversationId": None,
            "sourcePdf": str(pdf),
            "sourceSha256": source_hash,
            "outputPath": str(output),
            "pageCount": len(pages),
            "sourcePageCount": total_pages,
            "selectedPages": selected_pages,
            "pages": [
                {
                    "number": number,
                    "imagePath": str(page.resolve()),
                    "imageSha256": digest(page),
                    "draftPath": str((draft_dir / f"page-{number:04d}.txt").resolve()),
                    "draftSha256": None,
                    "viewed": False,
                    "viewedStepIdx": None,
                    "transcribed": False,
                    "transcribedStepIdx": None,
                }
                for number, page in zip(selected_pages, pages, strict=True)
            ],
            "pendingViews": {},
            "pendingDrafts": {},
        }
        write_json_atomic(manifest_path, manifest)

    print(f"Started guarded literal transcription: {pdf}")
    print(f"Pages: {len(pages)}")
    print(f"Output: {output}")
    print(f"Next view_file path: {pages[0].resolve()}")
    return 0


def status(args: argparse.Namespace) -> int:
    path = args.workspace.expanduser().resolve() / STATE_DIR / MANIFEST_NAME
    if not path.exists():
        print("No transcription session")
        return 1
    manifest = json.loads(path.read_text(encoding="utf-8"))
    viewed = sum(bool(page.get("viewed")) for page in manifest.get("pages", []))
    transcribed = sum(
        bool(page.get("transcribed")) for page in manifest.get("pages", [])
    )
    print(f"Active: {manifest.get('active', False)}")
    print(f"Source: {manifest['sourcePdf']}")
    print(f"Viewed: {viewed}/{manifest['pageCount']}")
    print(f"Transcribed: {transcribed}/{manifest['pageCount']}")
    print(f"Output: {manifest['outputPath']}")
    pending = next(
        (
            page
            for page in manifest.get("pages", [])
            if page.get("viewed") and not page.get("transcribed")
        ),
        None,
    )
    if pending:
        print(f"Write literal page draft: {pending['draftPath']}")
    else:
        next_page = next(
            (page for page in manifest.get("pages", []) if not page.get("viewed")), None
        )
        if next_page:
            print(f"Next view_file path: {next_page['imagePath']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--pdf", type=Path, required=True)
    start_parser.add_argument("--output", type=Path, required=True)
    start_parser.add_argument("--dpi", type=int, default=300)
    start_parser.add_argument(
        "--pages", help="optional source pages, for example 7-8,11"
    )
    subparsers.add_parser("status")
    args = parser.parse_args()
    return start(args) if args.command == "start" else status(args)


if __name__ == "__main__":
    raise SystemExit(main())
