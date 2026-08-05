#!/usr/bin/env python3
"""Dependency-free behavioral checks for literal transcription hooks."""

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
        session_dir = state_dir / "sessions" / "test"
        page_dir = session_dir / "pages"
        draft_dir = session_dir / "drafts"
        page_dir.mkdir(parents=True)
        draft_dir.mkdir()
        self.source = self.workspace / "scan.pdf"
        self.source.write_bytes(b"%PDF-test fixture")
        self.output = self.workspace / "transcript.md"
        self.source_numbers = [7, 11]
        self.pages = [page_dir / "page-1.png", page_dir / "page-2.png"]
        self.drafts = [draft_dir / "page-0001.txt", draft_dir / "page-0002.txt"]
        for number, page in enumerate(self.pages, 1):
            page.write_bytes(f"page-{number}".encode())
        self.manifest_path = state_dir / "session.json"
        self.manifest_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "active": True,
                    "conversationId": None,
                    "sourcePdf": str(self.source),
                    "sourceSha256": sha256(self.source),
                    "outputPath": str(self.output),
                    "pageCount": 2,
                    "pages": [
                        {
                            "number": self.source_numbers[number - 1],
                            "imagePath": str(page),
                            "imageSha256": sha256(page),
                            "viewAssets": [
                                {
                                    "kind": "full-page",
                                    "path": str(page),
                                    "sha256": sha256(page),
                                    "viewed": False,
                                }
                            ],
                            "draftPath": str(self.drafts[number - 1]),
                            "draftSha256": None,
                            "viewed": False,
                            "viewedStepIdx": None,
                            "transcribed": False,
                            "transcribedStepIdx": None,
                        }
                        for number, page in enumerate(self.pages, 1)
                    ],
                    "pendingViews": {},
                    "pendingDrafts": {},
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

    def view(self, number: int, step: int, *, error: str | None = None) -> None:
        result = self.call(
            "pre-tool",
            stepIdx=step,
            toolCall={
                "name": "view_file",
                "args": {"AbsolutePath": str(self.pages[number - 1])},
            },
        )
        self.assertEqual("allow", result["decision"])
        post_args = {"stepIdx": step}
        if error:
            post_args["error"] = error
        self.assertEqual({}, self.call("post-tool", **post_args))

    def transcribe(self, number: int, step: int, content: str) -> None:
        result = self.call(
            "pre-tool",
            stepIdx=step,
            toolCall={
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(self.drafts[number - 1]),
                    "CodeContent": content,
                },
            },
        )
        self.assertEqual("allow", result["decision"])
        self.drafts[number - 1].write_text(content, encoding="utf-8")
        self.assertEqual({}, self.call("post-tool", stepIdx=step))

    def state(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def test_view_must_be_followed_by_immediate_page_draft(self) -> None:
        self.view(1, 1)
        denied = self.call(
            "pre-tool",
            stepIdx=2,
            toolCall={
                "name": "view_file",
                "args": {"AbsolutePath": str(self.pages[1])},
            },
        )
        self.assertEqual("deny", denied["decision"])
        self.transcribe(1, 3, "• 시점: 허생전 → 3인칭\n• [판독 불가]\n")
        self.assertTrue(self.state()["pages"][0]["transcribed"])
        self.assertIn("• 시점: 허생전 → 3인칭", self.output.read_text(encoding="utf-8"))
        self.view(2, 4)

    def test_failed_view_does_not_advance(self) -> None:
        self.view(1, 1, error="render failed")
        self.assertFalse(self.state()["pages"][0]["viewed"])
        denied = self.call(
            "pre-tool",
            stepIdx=2,
            toolCall={
                "name": "write_to_file",
                "args": {"TargetFile": str(self.drafts[0])},
            },
        )
        self.assertEqual("deny", denied["decision"])

    def test_blocks_bypasses_wrong_writes_and_prior_page_edits(self) -> None:
        self.view(1, 1)
        for name in ("run_command", "generate_image", "call_mcp_tool"):
            result = self.call(
                "pre-tool", stepIdx=2, toolCall={"name": name, "args": {}}
            )
            self.assertEqual("deny", result["decision"])
        wrong = self.call(
            "pre-tool",
            stepIdx=3,
            toolCall={
                "name": "write_to_file",
                "args": {"TargetFile": str(self.output)},
            },
        )
        self.assertEqual("deny", wrong["decision"])
        edit = self.call(
            "pre-tool",
            stepIdx=4,
            toolCall={
                "name": "replace_file_content",
                "args": {"TargetFile": str(self.drafts[0])},
            },
        )
        self.assertEqual("deny", edit["decision"])

    def test_output_is_assembled_in_page_order_and_drafts_are_immutable(self) -> None:
        self.view(1, 1)
        self.transcribe(1, 2, "첫 줄\n- 둘째 줄")
        self.view(2, 3)
        self.transcribe(2, 4, "[빈 페이지]")
        expected = (
            "# 전사문\n\n## Page 7\n\n첫 줄\n- 둘째 줄\n\n## Page 11\n\n[빈 페이지]\n"
        )
        self.assertEqual(expected, self.output.read_text(encoding="utf-8"))
        self.drafts[0].write_text("변조", encoding="utf-8")
        result = self.call("stop")
        self.assertEqual("continue", result["decision"])
        self.assertIn("changed unexpectedly", result["reason"])

    def test_stop_only_after_every_page_is_transcribed(self) -> None:
        self.assertEqual("continue", self.call("stop")["decision"])
        self.view(1, 1)
        self.assertEqual("continue", self.call("stop")["decision"])
        self.transcribe(1, 2, "한 줄")
        self.view(2, 3)
        self.transcribe(2, 4, "두 줄")
        self.assertEqual("allow", self.call("stop")["decision"])
        self.assertFalse(self.state()["active"])

    def test_does_not_block_an_unrelated_conversation(self) -> None:
        self.view(1, 1)
        result = self.call(
            "pre-tool",
            conversationId="another-conversation",
            stepIdx=2,
            toolCall={"name": "run_command", "args": {"CommandLine": "git status"}},
        )
        self.assertEqual("allow", result["decision"])


if __name__ == "__main__":
    unittest.main()
