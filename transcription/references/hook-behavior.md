# Hook behavior and limits

The Hook records a page as viewed only after a successful `view_file` call whose `AbsolutePath`
matches the expected high-resolution full-page image and whose SHA-256 digest still matches the
session manifest. Each source page requires exactly one full-page view. It then blocks the next
page and every unrelated tool until `write_to_file` creates that page's literal draft at the
registered path. After a successful draft write, the Hook hashes the draft, marks it immutable,
and rebuilds the output deterministically before permitting the next page.

The Stop event verifies every view, every page draft hash, the source PDF hash, and byte-for-byte
output equality. The start command holds a filesystem lock throughout rendering so concurrent
starts cannot create competing active page sets.

This proves tool-call order, immediate per-page persistence, and file identity. No lifecycle Hook
can semantically prove that a model interpreted every glyph correctly. Conservative uncertainty
notation and the prohibition on fluent reconstruction therefore remain necessary.

Antigravity executes hooks synchronously from the directory containing `.agents/hooks.json`.
The installer therefore uses commands relative to `.agents/` and merges only the named
`transcription-page-verifier` hook, preserving other hook entries.
