# Output format

Write UTF-8 Markdown. Include every page exactly once and in order:

```markdown
# 전사문

## Page 1
<faithful transcription, or [빈 페이지]>

## Page 2
<faithful transcription>
```

Use the literal heading `## Page N` for each one-based page number. Keep visible section titles,
paragraphs, lists, tables, marginal notes, strike-throughs, and insertions as faithfully as
Markdown permits. Use `[취소선: ...]` and `[삽입: ...]` where plain Markdown would hide meaning.

Do not add a polished rewrite inside the transcript. If the user requests a summary, translation,
or normalized copy, add it after all page sections under `# 별도 해설`.
