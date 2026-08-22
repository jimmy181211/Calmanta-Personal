# Calmanta Personal agent rules

- For inbox monitoring, reply drafting, approvals, or browser-assisted sending, use the
  `calmanta-personal` skill in `.agents/skills/calmanta-personal/SKILL.md`.
- Reuse the sibling `../Calmanta-Official/backend` core. Do not copy or fork its safety rules here.
- Keep all account credentials, cookies, tokens, browser sessions, and local storage out of files and logs.
- Scheduled tasks may inspect and draft only. They must never send or publish.
- Keep output compact: deduplicate before drafting and show only new actionable drafts or escalations.
