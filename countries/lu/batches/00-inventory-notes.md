# Stage 2 Inventory & Classification Notes

## Method & SPARQL Queries

Discovered all consolidated legal instruments from Legilux Casemates SPARQL endpoint (`http://data.legilux.public.lu/sparqlendpoint`).

### SPARQL Query:
```sparql
SELECT ?work ?title ?fileUrl WHERE {
  ?work a <http://data.legilux.public.lu/resource/ontology/jolux#Consolidation> .
  ?work <http://data.legilux.public.lu/resource/ontology/jolux#isRealizedBy> ?expr .
  ?expr <http://data.legilux.public.lu/resource/ontology/jolux#isEmbodiedBy> ?manifest .
  ?manifest <http://data.legilux.public.lu/resource/ontology/jolux#isExemplifiedBy> ?fileUrl .
}
```

## Inventory Counts

- **Total Consolidated Legal Instruments Discovered:** 2,934
- **Digital Laws (XML/HTML):** 1,432
- **Stage 1B Published Laws (already on main):** 10
- **Skipped (PDF-only scans, no OCR in v1):** 1,502

## Batch ID Manifest Summary

| Batch File | Theme | Ingestible ID Count |
|---|---|---|
| `04-codes.txt` | 04-codes | 66 |
| `05-state-admin.txt` | 05-state-admin | 114 |
| `06-civil-family.txt` | 06-civil-family | 114 |
| `07-labor-social.txt` | 07-labor-social | 113 |
| `08-commercial-finance.txt` | 08-commercial-finance | 113 |
| `09-tax-finance.txt` | 09-tax-finance | 113 |
| `10-health-welfare.txt` | 10-health-welfare | 114 |
| `11-environment-energy.txt` | 11-environment-energy | 115 |
| `12-education-culture.txt` | 12-education-culture | 118 |
| `13-transport.txt` | 13-transport | 115 |
| `14-security-data.txt` | 14-security-data | 114 |
| `15-tail.txt` | 15-tail | 113 |

## Size Budget Assessment

- **Current Repo Size:** ~18 MiB
- **Estimated Retained Source Bytes for Digital Laws:** ~1,422 digital laws × ~250 KB XML = ~355 MiB (uncompressed)
- **Estimated Packed `.git` Growth:** ~90–120 MiB
- **Packed Repo Size Verdict:** **PASS** (well under the 900 MiB hard stop)
