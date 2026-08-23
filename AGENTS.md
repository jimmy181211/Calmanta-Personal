# Calmanta Personal agent rules

- For inbox monitoring, reply drafting, approvals, settings, voice-template management, or browser-assisted sending, use the
  `calmanta-personal` skill in `.agents/skills/calmanta-personal/SKILL.md`.
- Reuse the sibling `../Calmanta-Core/backend` package shipped with Personal. Never search for or
  modify Calmanta Official from this workspace.
- Keep all account credentials, cookies, tokens, browser sessions, and local storage out of files and logs.
- Scheduled tasks may inspect and draft only. They must never send or publish.
- A live browser send or publish requires an explicit approval of the specific item in the current interaction; every user-facing state must state the available natural-language next choices before action.
- Keep output compact: deduplicate before drafting and show only new actionable drafts or escalations.
