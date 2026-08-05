---
name: transcription
description: >-
  Scanned handwritten PDF files are transcribed page by page by visually inspecting every
  rendered page with view_file, without OCR, PDF text extraction, invented text, or skipped
  pages. Use this skill whenever the user asks Antigravity CLI to transcribe, decipher, or
  type up handwritten notes, forms, manuscripts, answers, or other scanned handwriting in PDF.
---

# Handwritten PDF transcription

Transcribe only marks that are visible on the supplied scan. Never reconstruct a plausible
document from context. Mark uncertain text explicitly instead of guessing.

## One-time workspace setup

This skill's hook must be installed because Antigravity loads workspace hooks only from
`<workspace>/.agents/hooks.json`, not from inside a skill folder.

If `.agents/hooks.json` does not contain `transcription-page-verifier`, run:

```bash
python3 .agents/skills/transcription/scripts/install_hooks.py --workspace .
```

Restart Antigravity CLI after installing or changing hooks, then confirm the hook in `/hooks`.
Use Antigravity CLI 1.1.10 or newer; that release fixes final `PostInvocation`/`Stop` hook
ordering needed for reliable completion checks.

## Required workflow

1. Resolve the real source PDF and requested output path. Do not create a substitute/sample PDF.
2. Read any separate user-supplied terminology or formatting reference before starting the
   guarded session.
3. Start a guarded session from the workspace root:

   ```bash
   python3 .agents/skills/transcription/scripts/transcription_session.py start \
     --pdf "/absolute/path/to/source.pdf" \
     --output "/absolute/path/to/transcript.md"
   ```

   This renders each page to an image without OCR or text extraction. Rendering is only a
   view adapter: the agent, not a recognition program, must read the handwriting.
4. Follow the injected hook instruction. Call `view_file` exactly once for the absolute image
   path shown for the next page. Process pages in numerical order. Do not use `read_file`,
   `pdftotext`, OCR, vision scripts, image-description services, or shell commands to obtain text.
5. Immediately retain a faithful draft for that page in reasoning/context. Preserve spelling,
   punctuation, line breaks, insertions, deletions, and visible structure when discernible.
   Use `[판독 불가]` for unreadable spans and `[불확실: 후보1/후보2]` only when the visible marks
   genuinely support those candidates. Never silently repair the author's language.
6. After every page has a successful `view_file` call, write the complete transcript only to
   the registered output path. Use the required page headings from
   [references/output-format.md](references/output-format.md).
7. Before answering the user, run no bypass command. Allow the Stop hook to validate page-view
   coverage, source integrity, output existence, and page headings. If it forces continuation,
   fix exactly the reported deficiency.

## Non-negotiable rules

- Treat blank pages as pages: view them and record `[빈 페이지]`.
- Distinguish transcription from interpretation. Put any requested commentary after the literal
  transcript and label it separately.
- Do not claim certainty that the scan does not support.
- Do not deactivate, edit, bypass, or delete the session state or hook during a transcription.
- If rendering fails or the scan is too poor to inspect, report the limitation; do not invent text.

For hook guarantees and limitations, see
[references/hook-behavior.md](references/hook-behavior.md).
