# Luxembourg Coverage

- **Publisher**: Service central de législation
- **Official entry point**: https://legilux.public.lu/
- **Data access**: Casemates open-data layer (`sparqlendpoint` + filestore). See [CASEMATES.md](CASEMATES.md).
- **Rights**: CC-BY-4.0 with attribution to Service central de législation, Luxembourg
- **Coverage**: Partial — Stage 1B ten-law slice
- **Supported families**: Codes, ordinary laws, grand-ducal regulations, constitution (LegalDocML/XML; one HTML Journal memorial)
- **Default language**: French (Constitution also published in German)
- **Source selection**: Prefer complete LegalDocML/XML; HTML retained when selected (see Stage 1B)
- **Known caveats**: The public Legilux website is an Angular SPA and must not be scraped. Use Casemates only.
- **Update command**: `uv run lex update lu` (or `--id <law-id>`)
- **Reviewer credits**: Maintainer review required before merge
- **Stage 1B selection**: [`STAGE_1B_SELECTION.md`](STAGE_1B_SELECTION.md) (approved with edits — implementation in this branch)

## Published laws

| ID | Title | Status | Notes |
|---|---|---|---|
| `lu/code-civil` | Code civil | official_consolidation | Stage 1A |
| `lu/loi-2006-09-21-n1` | Loi du 21 septembre 2006 (consol.) | official_consolidation | Ordinary law |
| `lu/rgd-2025-03-13-a93` | RGD du 13 mars 2025 (consol.) | official_consolidation | Regulation |
| `lu/code-commerce` | Code de commerce | official_consolidation | Second code |
| `lu/constitution` | Constitution | official_consolidation | FR + DE |
| `lu/loi-2024-07-31-a339` | Loi du 31 juillet 2024 | official_current | HTML source |
| `lu/code-penal` | Code pénal | official_consolidation | Irregular anchors |
| `lu/rgd-2024-12-20-a595` | RGD du 20 décembre 2024 (consol.) | official_consolidation | Rectification warning |
| `lu/code-travail` | Code du travail | official_consolidation | Large corpus |
| `lu/code-procedure-civile` | Nouveau Code de procédure civile | official_consolidation | Deep hierarchy |
