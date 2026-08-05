---
name: transcription
description: >-
  Scanned handwritten PDF files are transcribed literally, one visible line at a time, by
  inspecting each rendered page with view_file and immediately saving that page before viewing
  the next. It forbids OCR, summarization, normalization, inferred or invented text, and skipped
  pages. Use whenever the user asks Antigravity CLI to transcribe, decipher, or type up scanned
  handwriting in PDF with exact bullets, arrows, corrections, spelling, and line structure.
---

# Handwritten PDF transcription

Copy only marks visible in the supplied scan. Treat this as literal visual transcription, not
content generation. Never reconstruct a plausible answer from the printed question, surrounding
pages, expected subject knowledge, or memory.

## One-time workspace setup

This skill's hook must be installed because Antigravity loads workspace hooks only from
`<workspace>/.agents/hooks.json`, not from inside a skill folder.

For a workspace installation, if `.agents/hooks.json` does not contain
`transcription-page-verifier`, run:

```bash
python3 .agents/skills/transcription/scripts/install_hooks.py --workspace .
```

For a global installation under `~/.gemini/config/skills/transcription`, run once:

```bash
python3 ~/.gemini/config/skills/transcription/scripts/install_hooks.py --global
```

Restart Antigravity CLI after installing or changing hooks, then confirm the hook in `/hooks`.
Use Antigravity CLI 1.1.10 or newer; that release fixes final `PostInvocation`/`Stop` hook
ordering needed for reliable completion checks.

## Required workflow

1. Resolve the real source PDF and requested output path. Do not create a substitute/sample PDF.
2. Read any separate user-supplied terminology or formatting reference before starting the
   guarded session.
3. Start a guarded session from the workspace root using this skill's actual installation path.
   For the global installation, run:

   ```bash
   python3 ~/.gemini/config/skills/transcription/scripts/transcription_session.py start \
     --pdf "/absolute/path/to/source.pdf" \
     --output "/absolute/path/to/transcript.md"
   ```

   For a workspace installation, replace the script path with
   `.agents/skills/transcription/scripts/transcription_session.py`.

   If the user requests only specific source pages, add `--pages "7-8,11"`. Never select pages
   merely to avoid difficult handwriting.

   This renders each page at high resolution without OCR or text extraction. Rendering is only a
   view adapter: the agent, not a recognition program, must read the handwriting.
4. Follow the injected hook instruction. Call `view_file` for the exact next page image. Process
   pages numerically. Re-open the same image if necessary; never advance from memory.
5. Immediately after viewing a page, use `write_to_file` on the exact page-draft path injected by
   the Hook. No other page can be viewed first. Write visible text from top to bottom, retaining
   the author's physical line breaks. Apply these literal rules:
   - Preserve bullet symbols, numbering, arrows, indentation, misspellings, spacing distinctions,
     repeated words, unfinished sentences, and punctuation as seen.
   - Record crossed-out but legible text as `[취소: visible text]` at its original position.
   - Record insertions as `[삽입: visible text]` at their visible position.
   - Use `[판독 불가]`; never replace unclear writing with a contextually likely sentence.
   - Use `[빈 페이지]` only after visually confirming that no target writing is present.
   - Do not turn a list into prose, join separate lines, summarize, polish grammar, answer the
     printed question, or add facts absent from the pixels.
6. Let the Hook verify the page draft and assemble the registered output deterministically. It
   locks the completed draft and then permits the next `view_file` call. Never edit prior pages.
7. Do not use `read_file`, `pdftotext`, OCR, vision scripts, image-description services, or shell
   commands to obtain text. Before answering the user, allow the Stop Hook to verify every image,
   immutable page draft, source hash, and assembled output.

## Non-negotiable rules

- Prefer a literal awkward fragment over a fluent invented sentence.
- Treat blank pages as pages: view them and record `[빈 페이지]`.
- Distinguish transcription from interpretation. Put any requested commentary after the literal
  transcript and label it separately.
- Do not claim certainty that the scan does not support.
- Do not deactivate, edit, bypass, or delete the session state or hook during a transcription.
- If rendering fails or the scan is too poor to inspect, report the limitation; do not invent text.

For hook guarantees and limitations, see
[references/hook-behavior.md](references/hook-behavior.md).
