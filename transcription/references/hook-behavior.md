# Hook behavior and limits

The workspace hook records a page as viewed only after a successful `view_file` call whose
`AbsolutePath` exactly matches the next rendered page and whose SHA-256 digest still matches the
session manifest. It blocks out-of-order or unrelated file views, agent file writes before full
coverage, and shell commands while a session is active. The Stop event forces continuation until
all pages were viewed and the registered output contains every `## Page N` heading exactly once
and in order.

This proves tool-call coverage and file identity. No lifecycle hook can prove that a model paid
attention to every glyph or interpreted handwriting correctly. The skill's conservative
uncertainty notation remains necessary.

Antigravity executes hooks synchronously from the directory containing `.agents/hooks.json`.
The installer therefore uses commands relative to `.agents/` and merges only the named
`transcription-page-verifier` hook, preserving other hook entries.
