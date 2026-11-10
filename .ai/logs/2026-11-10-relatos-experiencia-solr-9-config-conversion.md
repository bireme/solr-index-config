# 2026-11-10 — relatos-experiencia Solr config converted from 5.5 to 9.9

Spec: `.ai/features/003-relatos-experiencia-solr-9-config-conversion.md`
Plan: `.ai/plans/005-convert-relatos-experiencia-solr-9-config.md`
Deployment notes: `relatos-experiencia/README.md`
Model: the best-practices conversion, `.ai/logs/2026-11-10-best-practices-solr-9-config-conversion.md`

## What was done

- Added `relatos-experiencia/conf` to the repository as it was on Solr 5.5 (baseline
  commit; byte-identical to `plugins-idx/solr_indexes/relatos-experiencia/conf`), then
  converted it in place.
- Removed the eight unreferenced files (`currency.xml`, `admin-extra*.html`,
  `_rest_managed.json`, `synonyms.txt`, `stopwords.txt`, `protwords.txt`).

### schema.xml

- Everything before `<fields>` was identical to the best-practices 5.5 schema, so it was
  replaced with the converted best-practices block verbatim: version `1.6`, Point types
  with docValues, `string` with docValues, `plong`, the seven DeCS types removed,
  `WordDelimiterGraphFilterFactory` (+ `FlattenGraphFilterFactory` on the `text` index
  analyzer), `omitPositions` on `textSpell`, `useDocValuesAsStored="false"` on `ignored`.
- Fields: `_version_` → `plong`; `docValues="false"` on the stored-only date strings
  `start_date`, `end_date`, `partial_date`, `other_date`. Nothing else changed (scripted
  comparison: 35 fields, catch-all dynamic field and 5 copyFields identical).
- `<defaultSearchField>` and `<solrQueryParser>` removed.

### solrconfig.xml

Copy of the converted `best-practices/conf/solrconfig.xml` with relatos-experiencia's four
facet fields (`population_group`, `thematic_area`, `country`, `collection`); the diff
between the two files is only the facet list. Commit policy unchanged: hard commit 15 s
(`openSearcher=false`), soft commit off, updateLog on.

## Smoke test (stock `solr:9.9`, Solr 9.9.0, no jar, no DeCS index)

42/42 checks passed: core load with no errors or core-specific warnings; JSON and XML
updates; documents invisible before an explicit commit (after 20 s) and visible after;
bare queries find terms from each of `title`, `notes`, `description`, `fulltext`,
`issue` and not from non-copied fields; AND on `/select` and `/query`; accented,
hyphenated and phrase queries; all 4 facets; `fq` on `status`, `country`,
`thematic_area` and combined; `fl=*` without `tw`; 40,000-character values in
`other_date` and `lessons_learned`; catch-all dynamic field; string sort; `/related`,
`/terms`, `/export`, `/admin/ping`; `/config` commit settings; tlog present.
`xmllint --noout` passes on both files.

The first run had two test-side failures, no config changes: a facet tie ordering
assumption, and `/query` expected to search `tw`.

## Notes for whoever deploys or maintains this core

- **Explicit commits are required** for documents to become searchable (unchanged from 5.5).
- `/query` has `df=text` (as in 5.5, where the handler default overrode the schema's
  `defaultSearchField`): bare queries there search the catch-all `text` field, not `tw`.
- The date fields are stored-only strings: not searchable, filterable or sortable, as in 5.5.
- `sort=title asc` does not sort alphabetically (`title` is a tokenized `text` field).
- `/export` accepts only docValues fields (the indexed `string` fields).
- `best-practices/README.md` states that default-field queries were validated on
  `/query`; best-practices' `/query` also has `df=text`, so that sentence is inaccurate
  (not changed here).

## Not verified

- The real requests of the application that uses this core (not available on this machine).
- `plugins-idx` (still `bireme/solr:5.5.5`) was not changed; a full reindex is required
  when it moves to Solr 9.
