#!/usr/bin/env python3
"""Install this skill's named Antigravity hook without replacing unrelated hooks."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

HOOK_NAME = "transcription-page-verifier"


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="install into ~/.gemini/config for all Antigravity workspaces",
    )
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parent.parent
    if args.global_install:
        customization_root = (Path.home() / ".gemini" / "config").resolve()
    else:
        workspace = args.workspace.expanduser().resolve()
        customization_root = workspace / ".agents"
    expected = customization_root / "skills" / "transcription"
    if skill_dir != expected:
        raise SystemExit(
            "Install this folder under the selected customization root before installing its hook.\n"
            f"Expected: {expected}\nFound: {skill_dir}"
        )

    template = json.loads((skill_dir / "hooks.json").read_text(encoding="utf-8"))
    hook_path = customization_root / "hooks.json"
    if hook_path.exists():
        try:
            current = json.loads(hook_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise SystemExit(
                f"Refusing to overwrite invalid JSON at {hook_path}: {error}"
            )
        if not isinstance(current, dict):
            raise SystemExit(f"Refusing to overwrite non-object JSON at {hook_path}")
    else:
        current = {}

    current[HOOK_NAME] = template[HOOK_NAME]
    write_json_atomic(hook_path, current)
    print(f"Installed {HOOK_NAME} in {hook_path}")
    print("Restart Antigravity CLI and confirm it with /hooks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
