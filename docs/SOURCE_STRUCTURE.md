# Source structure and maintenance

- `calmanta_personal/cli_parser.py`: command names and argument contracts.
- `calmanta_personal/cli.py`: command dispatch and execution.
- `calmanta_personal/profile_rules.py`: settings validation and constants.
- `calmanta_personal/profile_panels.py`: settings presentation.
- `calmanta_personal/profile_settings.py`: persistence and compatibility.
- `tests/`: temporary-directory workflow fixtures.
- `config/`, `data/`, `staging/`: configuration and local runtime state.

Core stays a sibling package. Keep legacy public imports available when
moving internals. Tests must use fixtures, never the user's profile or DB.

## Readability rules

Keep authored code and comments within 80 characters per line. Use the
project formatter, then run this portable development check from the root:

```text
python tooling/check_source_width.py
```

The checker excludes generated output, vendor code, archived releases,
runtime data, and resources. It does not rewrite files. JSON, SQL, Markdown,
lockfiles, and installer localization are data/documents, not code-width
targets. Keep their values and historical provenance intact.

Group modules by responsibility and dependency direction. Keep public entry
points stable, avoid forwarding-only layers, and split a file when the parts
have independent responsibilities. Comments explain purpose, invariants,
units, timing, or non-obvious constraints; do not narrate obvious statements.
Prefer named helpers to deeply nested expressions or repeated magic values.

After moving code, verify public imports, builds, fixture tests, and affected
screens. Compare persisted formats, query order, translations, and input/output
contracts. Formatting checks do not establish behavioral equivalence.
