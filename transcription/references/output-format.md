# Output format

The Hook writes UTF-8 Markdown by concatenating immutable, per-page UTF-8 text drafts. It adds
every page heading exactly once and in order:

```markdown
# 전사문

## Page 1
<literal visible lines, or [빈 페이지]>

## Page 2
<faithful transcription>
```

Do not put a `## Page N` heading in a page draft; the Hook supplies it. Preserve physical lines,
bullets, arrows, numbering, indentation, marginal notes, strike-throughs, and insertions. Use
`[취소: ...]`, `[삽입: ...]`, and `[판독 불가]` only as visual annotations.

Do not put a rewrite, summary, evaluation, inferred answer, or explanation in a page draft.
