# Luxembourg Coverage

- **Publisher**: Service central de législation
- **Official entry point**: https://legilux.public.lu/
- **Data access**: Casemates open-data layer (`sparqlendpoint` + filestore). See [CASEMATES.md](CASEMATES.md).
- **Rights**: CC-BY-4.0 with attribution to Service central de législation, Luxembourg
- **Coverage**: Partial — one published law
- **Supported families**: Codes (LegalDocML/XML consolidations via Casemates)
- **Default language**: French
- **Source selection**: Prefer complete LegalDocML/XML; fall back only when XML is incomplete
- **Known caveats**: The public Legilux website is an Angular SPA and must not be scraped. Use Casemates only.
- **Update command**: `uv run lex update lu --id lu/code-civil`
- **Reviewer credits**: Maintainer review required before merge
- **Stage 1B selection**: [`STAGE_1B_SELECTION.md`](STAGE_1B_SELECTION.md) (approved with edits — HTML retained for `loi-2024-07-31-a339`)

## Published laws

| ID | Title | Status |
|---|---|---|
| `lu/code-civil` | Code civil | official_consolidation |
