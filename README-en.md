# Calmanta Personal

Documentation sync date: 2026-08-23

Calmanta Personal is a personal companion designed to work with local ChatGPT/Codex. It uses the separate `Calmanta-Core` next to it for account-material filtering, risk classification, sensitive-topic detection, tone rules, and draft safety checks. Personal itself handles local persistence, ChatGPT workflows, and approval records. Calmanta Official is not required at runtime.

## How the two versions are divided

- `Calmanta-Core`: The smallest rule package bundled with Personal. It does not include a server, database, Android, or platform-account capabilities.
- `Calmanta-Personal`: The local personal version. It uses ChatGPT/Codex as the “model and operating framework,” and stores data on the local machine.

Place the two directories side by side:

```text
Calmanta-Personal-Package/
├── Calmanta-Core/
└── Calmanta-Personal/
```

You can also use the `CALMANTA_CORE_DIR` environment variable to point to the `Calmanta-Core` directory.

## Where local data is stored

- Comments, direct messages, drafts, approvals, and events: `data/calmanta-personal.db` (SQLite)
- Images or evidence files: `data/objects/` (deduplicated with SHA-256)
- Temporary observations and decisions: `staging/`
- Public example settings: `config/profile.example.json`
- Personal tone, platform, and approval settings: `config/profile.local.json` (local only, ignored by Git)

`data/` and `staging/` are not committed to Git by default. Personal does not store account passwords, Cookies, Tokens, browser sessions, or Local Storage; the `Calmanta-Core` filter rejects these fields.

## Quick start

Run in this directory:

```bash
python -m calmanta_personal init
python -m unittest discover -s tests -v
```

If `python` is not on PATH, let ChatGPT/Codex use its bundled Python runtime. You do not need to install a database, object storage, or model SDK.

The project’s skill is located at `.agents/skills/calmanta-personal/`. After opening ChatGPT/Codex from this directory, daily tasks only need to call `$calmanta-personal`; fixed rules do not need to be repeated each day, which reduces token use.

## Workflow

1. The user logs in to Instagram and Xiaohongshu in their own browser.
2. ChatGPT checks only visible new messages/comments and does not touch authentication materials.
3. Run `filter-new` first to exclude items already seen in SQLite.
4. ChatGPT first determines the risk level and comment category; the user chooses between drafting automatically and recording only based on the risk level.
5. `ingest` saves the result locally. Record-only items do not create drafts; threats, privacy issues, and sensitive matters always go to the user first.
6. `OK <ID>` records approval, but the command line itself never sends anything.
7. Browser actions can continue only when the user explicitly asks in the current interaction to send or publish. After the platform shows success, use `complete <ID> --confirm SENT` to record it.

Scheduled tasks always stop at step 5 and must not send or publish.

## Common commands

```bash
python -m calmanta_personal settings show
python -m calmanta_personal settings preview --set low=generate_draft
python -m calmanta_personal settings save --set low=generate_draft --confirm SAVE
python -m calmanta_personal filter-new --input staging/observed.json --output staging/new.json
python -m calmanta_personal ingest --input staging/decisions.json
python -m calmanta_personal list --state draft_pending_review
python -m calmanta_personal approve <ID> --confirm OK
python -m calmanta_personal reject <ID>
python -m calmanta_personal complete <ID> --confirm SENT
python -m calmanta_personal put-object <file path>
```

In ChatGPT/Codex, say “open settings” to view the current handling for the four risk levels and “my tone templates.” After the user requests a change, Personal first shows an unsaved preview; it writes only after the user explicitly says “save settings.” Each level supports only “generate draft” and “record only.” Settings affect only newly processed comments, and mandatory safety rules always take priority.

The user can also say “add tone template” or “manage tone templates.” A template can select multiple of seven fixed replyable comment categories: friendly or ordinary conversation, questions, factual corrections, ordinary doubts or disagreement, unverified accusations, insults or personal attacks, and ongoing harassment. Templates change only the wording; unbound categories continue using the base tone. They cannot rewrite AI classification, risk levels, or mandatory safety rules.

Whenever settings, templates, previews, template management, or a review card are opened, filled out, previewed, managed, or viewed, Personal first explains the current state and uses “You can now:” to list the next steps the user can say directly. It does not assume that the user knows commands, IDs, or JSON, and it does not automatically save, enable, delete, send, or publish anything.

## Boundaries

Personal is an experimental assistant for low-frequency use with the user’s own accounts and visible-page content only. Website changes, disconnections, CAPTCHAs, risk controls, or platform rules may cause a check to fail. Do not bypass CAPTCHAs, risk controls, or access controls; do not scrape in bulk; and do not give login credentials to the project. For stable commercial integrations, use official platform APIs, OAuth, or compliant partners.
