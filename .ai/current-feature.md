# Current Feature: Convert relatos-experiencia Solr config from 5.5 to 9.9

<!-- Feature Name -->

## Status

<!-- Not Started|In Progress|Completed -->

Completed

## Goals

<!-- Goals & requirements -->

- The `relatos-experiencia` core starts on a stock Solr 9.9 (Lucene 9.12.2) with no schema/config errors and no configuration warnings, without any custom jar or DeCS index.
- Every field, the dynamic field and all five copyFields still exist with the same name and the same stored/indexed/multiValued semantics.
- Queries behave as before: default field `tw`, default operator AND, the 4 `/select` facet fields, `/related`, `/terms`, `/admin/ping`.
- Commit policy unchanged: 15 s hard commit (`openSearcher=false`), soft commit off, updateLog on.
- `relatos-experiencia/conf` contains only `schema.xml` and `solrconfig.xml`.
- `relatos-experiencia/README.md` documents deployment and what changed.
- Acceptance: the local `solr:9.9` Docker smoke test in the spec passes and `xmllint --noout` passes on both files.

## Notes

<!-- Any extra notes -->

- Full spec: [`.ai/features/003-relatos-experiencia-solr-9-config-conversion.md`](features/003-relatos-experiencia-solr-9-config-conversion.md)
- Model: the converted `best-practices/conf` (feature 002); all of 002's decisions are reused. `relatos-experiencia/solrconfig.xml` (5.5) differs from the best-practices 5.5 baseline only in the facet list, so the converted file should differ from `best-practices/conf/solrconfig.xml` only in the facet list (`population_group`, `thematic_area`, `country`, `collection`).
- `relatos-experiencia/conf` is byte-identical to the deployed `plugins-idx/solr_indexes/relatos-experiencia/conf`.
- DeCS types: remove `decs`, `decs_simple`, `decs_keyword`, `decs_code`, `decs_qualifier`, `decs_authorized_category`, `text_with_decs`; no field uses them. Other unused types are kept.
- Process: baseline commit of the 5.5 files, then convert in place on a feature branch; delete the eight unreferenced files; config files + README only.
- Schema: version `1.6`, `Trie*Field` → `*PointField` with docValues, `string` with docValues, `plong` for `_version_`, `WordDelimiterGraphFilterFactory` (+ `FlattenGraphFilterFactory` on the `text` index analyzer), `omitPositions="true"` on `textSpell`, `useDocValuesAsStored="false"` on `ignored`, remove `<defaultSearchField>` and `<solrQueryParser>`.
- The four stored-only date strings (`start_date`, `end_date`, `partial_date`, `other_date`) get `docValues="false"` (fi-admin's 32766-byte fix). The stored-only `text` fields need nothing.
- `status` is an indexed `string` here (unlike best-practices): smoke test must cover `fq` on it.
- solrconfig: `luceneMatchVersion` `9.12`, drop `numVersionBuckets` and cache classes, `q.op=AND` on `/select` and `/query`, remove `<jmx/>`, `enableRemoteStreaming` and the explicit `/export` handler.
- Smoke test runs with no `lib/` and no DeCS mount; must cover all five copyField sources, a >32766-byte value in `other_date`, and visibility only after an explicit commit.
- Out of scope: `plugins-idx` (still `bireme/solr:5.5.5`; its health check only pings best-practices), the client application, tuning, new fields.
- Risks: the client's real query patterns are unknown (application not on this machine); a full reindex is mandatory on Solr 9.

## Detailed Plan

<!-- Link to detailed plan file -->

[005-convert-relatos-experiencia-solr-9-config.md](plans/005-convert-relatos-experiencia-solr-9-config.md)

## History

<!-- Keep this updated. Earliest to latest -->
- 2026-11-10: Starting Convert fi-admin Solr config from 5.5 to 9.9 — following plan [003-convert-fi-admin-solr-9-config.md](plans/003-convert-fi-admin-solr-9-config.md)
- 2026-11-10: Converted `schema.xml` and `solrconfig.xml`, removed 8 unreferenced files, added `fi-admin/README.md`. Smoke test on `solr:9.9` (Solr 9.9.0) with `iahx-analyzer-20260119.jar` and the local DeCS index passed: core load, indexing per `django_ct`, AND/`df=tw`, `fq`, facets, sorts, date ranges, DeCS expansion, `/related`, `/terms`, `/export`, `/admin/ping`.
- 2026-11-10: Deviations from the plan found by the smoke test: removed `<jmx/>` (no longer supported), removed `enableRemoteStreaming` and did not add `enableStreamBody` (both ignored by Solr 9; system properties instead), removed the explicit `/export` handler (it shadowed Solr 9's implicit one and returned a plain 10-row search). `portal/conf/solrconfig.xml` has the same three items and was not touched.
- 2026-11-10: Review: found that docValues on the five `indexed="false"` string fields rejected values over 32766 bytes (Solr 5.5 accepted them); set `docValues="false"` on those fields and re-verified on `solr:9.9`. Hyphenated-term queries (`covid-19`, `saude-publica`) checked and working with AND.
- 2026-11-10: Completed **Convert fi-admin Solr config from 5.5 to 9.9**. `fi-admin/conf` (schema.xml, solrconfig.xml) now loads on Solr 9.9 with portal's DeCS filter chains, Point fields and docValues, `q.op=AND` in the handlers, and fi-admin's original commit policy; deployment notes in `fi-admin/README.md`. Merged to `main` and pushed. Spec: [001](features/001-fi-admin-solr-9-config-conversion.md), plan: [003](plans/003-convert-fi-admin-solr-9-config.md), log: [2026-11-10](logs/2026-11-10-fi-admin-solr-9-config-conversion.md). Open: parity with the 5.5 core and FI-Admin (pysolr/Haystack) against Solr 9 are untested; `fi-admin-idx` still runs Solr 5.5.
- 2026-11-10: Starting Convert best-practices Solr config from 5.5 to 9.9 — following plan [004-convert-best-practices-solr-9-config.md](plans/004-convert-best-practices-solr-9-config.md)
- 2026-11-10: Converted best-practices `schema.xml` and `solrconfig.xml`, removed 8 unreferenced files and the 7 unused DeCS field types, added `best-practices/README.md`. `solrconfig.xml` now differs from fi-admin's only in commit timing and the facet list. Smoke test on stock `solr:9.9` (Solr 9.9.0, no jar, no DeCS index) passed on the first run: core load with no warnings, JSON/XML indexing, no visibility before explicit commit, AND/`df=tw`, accents/hyphens/phrases, all 11 facets, `fq`, `fl=*`, catch-all field, string sort, 48,000-character stored-only text value, `/related`, `/terms`, `/export`, `/admin/ping`. No deviations from the plan.
- 2026-11-10: Review: no defects found, no code changes. Extra probes on `solr:9.9` passed: wildcard/prefix, boolean operators, edismax with `qf`, paging, highlighting, tagged/excluded facets, delete by id, `wt=xml|php|phps`. Noted: `sort=title asc` runs without error but orders by an indexed token, not alphabetically (title is a tokenized `text` field and there is no sort field); `fq=status:1` returns 0 results because `status` is stored-only, as in 5.5. Corrected the field count in the spec and plan (32, not 33).
- 2026-11-10: Completed **Convert best-practices Solr config from 5.5 to 9.9**. `best-practices/conf` (schema.xml, solrconfig.xml) now loads on a stock Solr 9.9 with no custom jar or DeCS index: Point fields and docValues, unused DeCS types removed, `q.op=AND` in the handlers, original commit policy (explicit commits required); deployment notes in `best-practices/README.md`. Merged to `main` and pushed. Spec: [002](features/002-best-practices-solr-9-config-conversion.md), plan: [004](plans/004-convert-best-practices-solr-9-config.md), log: [2026-11-10](logs/2026-11-10-best-practices-solr-9-config-conversion.md). Open: the client application's real requests are untested; `plugins-idx` still runs Solr 5.5.
- 2026-11-10: Starting Convert relatos-experiencia Solr config from 5.5 to 9.9 — following plan [005-convert-relatos-experiencia-solr-9-config.md](plans/005-convert-relatos-experiencia-solr-9-config.md)
- 2026-11-10: Converted relatos-experiencia `schema.xml` and `solrconfig.xml`, removed 8 unreferenced files and the 7 unused DeCS field types, added `relatos-experiencia/README.md`. `solrconfig.xml` differs from best-practices' only in the facet list; schema differs from the 5.5 baseline only in `_version_` → `plong` and `docValues="false"` on the four stored-only date strings (scripted check). Smoke test on stock `solr:9.9` (Solr 9.9.0, no jar, no DeCS index): 42/42 checks passed — core load with no warnings, JSON/XML indexing, no visibility before explicit commit, `df=tw` with all five copyField sources, AND, accents/hyphens/phrases, 4 facets, `fq` on `status`/`country`/`thematic_area`, `fl=*`, catch-all field, string sort, 40,000-character values in `other_date` and `lessons_learned`, `/related`, `/terms`, `/export`, `/admin/ping`, commit settings. Deviation from the plan (test only, no config change): `/query` has `df=text` in the 5.5 baseline, so a bare query there searches the catch-all `text` field, not `tw`; kept as is and documented in the README; AND on `/query` verified with an explicit field.
- 2026-11-10: Review: no defects found, no config changes. Diff checked against goals: schema types identical to converted best-practices, fields differ from 5.5 only as intended, solrconfig differs from best-practices only in facets, no scope creep. Indexed `string` fields with docValues keep the same 32766-byte limit they already had as indexed terms in 5.5, so no regression there. Corrected the spec's acceptance wording: `/query` uses `df=text` (unchanged from 5.5), so bare queries there do not search `tw`. Noted outside this feature: `best-practices/README.md` says default-field queries were validated on `/query`, but best-practices' `/query` also has `df=text`.
