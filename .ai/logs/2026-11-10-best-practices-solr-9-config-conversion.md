# 2026-11-10 — best-practices Solr config converted from 5.5 to 9.9

Spec: `.ai/features/002-best-practices-solr-9-config-conversion.md`
Plan: `.ai/plans/004-convert-best-practices-solr-9-config.md`
Deployment notes: `best-practices/README.md`
Model: the fi-admin conversion, `.ai/logs/2026-11-10-fi-admin-solr-9-config-conversion.md`

## What was done

- Added `best-practices/conf` to the repository as it was on Solr 5.5 (baseline commit),
  then converted it in place.
- Removed the eight unreferenced files (`currency.xml`, `admin-extra*.html`,
  `_rest_managed.json`, `synonyms.txt`, `stopwords.txt`, `protwords.txt`).

### schema.xml

- Version `1.5` → `1.6`.
- `Trie*Field` → `*PointField` with docValues; `string` with docValues; new `plong` type
  for `_version_`.
- Removed the seven DeCS field types (`decs`, `decs_simple`, `decs_keyword`, `decs_code`,
  `decs_qualifier`, `decs_authorized_category`, `text_with_decs`). No field used them, so
  the core needs no `iahx-analyzer` jar and no DeCS index.
- `WordDelimiterFilterFactory` → `WordDelimiterGraphFilterFactory` (same parameters) in
  `text` and `textSpell`; `FlattenGraphFilterFactory` added to the `text` index analyzer.
- `status` (stored-only `int`) set to `docValues="false"`.
- `<defaultSearchField>` and `<solrQueryParser>` removed.
- All 32 fields, the catch-all dynamic field and both copyFields kept.

### solrconfig.xml

Same edits as fi-admin: `luceneMatchVersion` `9.12`; `q.op=AND` on `/select` and
`/query`; cache `class` attributes removed; `numVersionBuckets`, `<jmx/>`,
`enableRemoteStreaming` and the explicit `/export` handler removed. After conversion the
file differs from `fi-admin/conf/solrconfig.xml` only in commit timing and the
`facet.field` list. Commit policy unchanged: hard commit 15 s (`openSearcher=false`),
soft commit off, updateLog on.

## Smoke test (stock `solr:9.9`, Solr 9.9.0, no jar, no DeCS index)

Passed on the first run, no deviations from the plan:

- Core loads with no errors and no configuration warnings.
- JSON and XML updates; a 48,000-character value in a stored-only `text` field is accepted.
- A document added without commit is still invisible after 20 s and visible after
  `commit=true`.
- Default field `tw` (title + introduction) and AND semantics on `/select` and `/query`.
- Accented, hyphenated and phrase queries; wildcard/prefix; boolean operators; edismax
  with `qf`; paging; highlighting.
- All 11 `/select` facets, per-field `facet.limit`, tagged/excluded facets, `fq` on facet
  fields.
- `fl=*` returns stored fields (including `status`) and not `tw`; catch-all dynamic field.
- `/related`, `/terms`, `/export`, `/admin/ping`; `wt=xml|php|phps`; delete by id.

## Notes for whoever deploys or maintains this core

- **Explicit commits are required** for documents to become searchable (unchanged from 5.5).
- `sort=title asc` does not fail but does not sort alphabetically: `title` is a tokenized
  `text` field and the schema has no sort field. If title sorting is needed, add a
  single-token sort field fed by copyField (as `title_sort` in fi-admin).
- `fq=status:…` matches nothing: `status` is stored-only, as in the 5.5 schema.
- `/export` accepts only docValues fields (the `string` fields).

## Not verified

- The real requests of the application that uses this core (not available on this machine).
- `plugins-idx` (still `bireme/solr:5.5.5`) was not changed; a full reindex is required
  when it moves to Solr 9. Its other core, `relatos-experiencia`, was not looked at.
