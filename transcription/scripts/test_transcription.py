#!/usr/bin/env python3
"""Dependency-free behavioral checks for the transcription lifecycle hook."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "transcription_hook.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        state_dir = self.workspace / ".transcription"
        page_dir = state_dir / "sessions" / "test" / "pages"
        page_dir.mkdir(parents=True)
        self.source = self.workspace / "scan.pdf"
        self.source.write_bytes(b"%PDF-test fixture")
        self.output = self.workspace / "transcript.md"
        self.pages = [page_dir / "page-1.png", page_dir / "page-2.png"]
        for number, page in enumerate(self.pages, 1):
            page.write_bytes(f"page-{number}".encode())
        self.manifest_path = state_dir / "session.json"
        self.manifest_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "active": True,
                    "conversationId": None,
                    "sourcePdf": str(self.source),
                    "sourceSha256": sha256(self.source),
                    "outputPath": str(self.output),
                    "pageCount": 2,
                    "pages": [
                        {
                            "number": number,
                            "imagePath": str(page),
                            "imageSha256": sha256(page),
                            "viewed": False,
                            "viewedStepIdx": None,
                        }
                        for number, page in enumerate(self.pages, 1)
                    ],
                    "pendingViews": {},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def call(self, event: str, **extra: object) -> dict:
        payload = {
            "conversationId": "conversation-test",
            "workspacePaths": [str(self.workspace)],
            **extra,
        }
        process = subprocess.run(
            [sys.executable, str(HOOK), event],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(process.stdout)

    def view(self, number: int, step: int) -> None:
        allowed = self.call(
            "pre-tool",
            stepIdx=step,
            toolCall={
                "name": "view_file",
                "args": {"AbsolutePath": str(self.pages[number - 1])},
            },
        )
        self.assertEqual("allow", allowed["decision"])
        self.assertEqual({}, self.call("post-tool", stepIdx=step))

    def test_requires_order_and_successful_post_event(self) -> None:
        denied = self.call(
            "pre-tool",
            stepIdx=1,
            toolCall={
                "name": "view_file",
                "args": {"AbsolutePath": str(self.pages[1])},
            },
        )
        self.assertEqual("deny", denied["decision"])
        self.view(1, 2)
        state = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(state["pages"][0]["viewed"])
        self.assertFalse(state["pages"][1]["viewed"])

    def test_blocks_all_bypasses_and_early_output(self) -> None:
        for name in ("run_command", "generate_image", "call_mcp_tool"):
            result = self.call(
                "pre-tool", stepIdx=1, toolCall={"name": name, "args": {}}
            )
            self.assertEqual("deny", result["decision"])
        result = self.call(
            "pre-tool",
            stepIdx=2,
            toolCall={
                "name": "write_to_file",
                "args": {"TargetFile": str(self.output)},
            },
        )
        self.assertEqual("deny", result["decision"])

    def test_does_not_block_an_unrelated_conversation(self) -> None:
        self.view(1, 1)
        result = self.call(
            "pre-tool",
            conversationId="another-conversation",
            stepIdx=2,
            toolCall={"name": "run_command", "args": {"CommandLine": "git status"}},
        )
        self.assertEqual("allow", result["decision"])

    def test_stop_requires_all_pages_and_headings(self) -> None:
        self.assertEqual("continue", self.call("stop")["decision"])
        self.view(1, 1)
        self.view(2, 2)
        self.output.write_text("# 전사문\n\n## Page 1\na\n", encoding="utf-8")
        self.assertEqual("continue", self.call("stop")["decision"])
        self.output.write_text(
            "# 전사문\n\n## Page 1\na\n\n## Page 2\n[빈 페이지]\n", encoding="utf-8"
        )
        self.assertEqual("allow", self.call("stop")["decision"])
        state = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(state["active"])


if __name__ == "__main__":
    unittest.main()
