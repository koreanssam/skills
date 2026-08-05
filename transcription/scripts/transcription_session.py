#!/usr/bin/env python3
"""Create and inspect a page-verified handwritten-PDF transcription session."""

from __future__ import annotations

import argparse
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


def render_pages(pdf: Path, page_dir: Path, dpi: int) -> list[Path]:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise SystemExit(
            "pdftoppm is required only to render page images (no OCR/text extraction). "
            "Install Poppler, then retry."
        )
    page_dir.mkdir(parents=True, exist_ok=False)
    prefix = page_dir / "page"
    process = subprocess.run(
        [executable, "-png", "-r", str(dpi), str(pdf), str(prefix)],
        text=True,
        capture_output=True,
        check=False,
    )
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

    manifest_path = workspace / STATE_DIR / MANIFEST_NAME
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("active"):
            raise SystemExit(
                f"An active session already exists for {previous.get('sourcePdf')}. "
                "Finish it before starting another."
            )

    source_hash = digest(pdf)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_dir = workspace / STATE_DIR / "sessions" / f"{stamp}-{source_hash[:12]}"
    pages = render_pages(pdf, session_dir / "pages", args.dpi)
    expected = list(range(1, len(pages) + 1))
    actual = [page_number(path) for path in pages]
    if actual != expected:
        raise SystemExit(f"Rendered pages are not contiguous: {actual}")

    manifest = {
        "version": 1,
        "active": True,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "conversationId": None,
        "sourcePdf": str(pdf),
        "sourceSha256": source_hash,
        "outputPath": str(output),
        "pageCount": len(pages),
        "pages": [
            {
                "number": number,
                "imagePath": str(path.resolve()),
                "imageSha256": digest(path),
                "viewed": False,
                "viewedStepIdx": None,
            }
            for number, path in enumerate(pages, 1)
        ],
        "pendingViews": {},
    }
    write_json_atomic(manifest_path, manifest)
    print(f"Started guarded transcription: {pdf}")
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
    viewed = sum(bool(page["viewed"]) for page in manifest["pages"])
    print(f"Active: {manifest.get('active', False)}")
    print(f"Source: {manifest['sourcePdf']}")
    print(f"Viewed: {viewed}/{manifest['pageCount']}")
    print(f"Output: {manifest['outputPath']}")
    next_page = next((page for page in manifest["pages"] if not page["viewed"]), None)
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
    start_parser.add_argument("--dpi", type=int, default=220)
    subparsers.add_parser("status")
    args = parser.parse_args()
    return start(args) if args.command == "start" else status(args)


if __name__ == "__main__":
    raise SystemExit(main())
