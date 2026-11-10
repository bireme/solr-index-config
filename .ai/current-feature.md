# Current Feature: Convert fi-admin Solr config from 5.5 to 9.9

<!-- Feature Name -->

## Status

<!-- Not Started|In Progress|Completed -->

Completed

## Goals

<!-- Goals & requirements -->

- The `fi-admin` core starts on Solr 9.9 (Lucene 9.12.2) with no schema or config errors.
- Every field, dynamic field and copyField of the 5.5 schema still exists with the same name and the same stored/indexed/multiValued semantics.
- fi-admin's queries keep working unchanged: default field `tw`, default operator AND, the `/select` facet list, `fq` on `status` / `django_ct`, sort on `title_sort`, `/related`.
- Incremental indexing from Django/Haystack keeps its timing: hard commit 10 min (`openSearcher=false`), soft commit 60 s, updateLog enabled.
- `fi-admin/conf` contains only `schema.xml` and `solrconfig.xml`, like `portal/conf`.
- `fi-admin/README.md` documents deployment: Solr 9.9, analyzer jar location, DeCS index path, mandatory full reindex.
- Acceptance: the local `solr:9.9` Docker smoke test in the spec passes (core load, sample indexing per `django_ct`, query patterns) and `xmllint --noout` passes on both files.

## Notes

<!-- Any extra notes -->

- Full spec: [`.ai/features/001-fi-admin-solr-9-config-conversion.md`](features/001-fi-admin-solr-9-config-conversion.md)
- Model: `portal/conf` is the validated Solr 9 reference for syntax, field-type classes and DeCS analysis chains.
- DeCS types: replace `org.bireme.dia.analysis.*Analyzer` classes with portal's `org.bireme.dia.filters.SynonymFilterFactory` chains.
- solrconfig scope: compatibility only; portal's bulk-indexing tuning and its `process-specific-clusters` update chain are not copied.
- Layout: commit `fi-admin/conf` as-is first (5.5 baseline), then convert in place on a feature branch.
- Cleanup: delete `currency.xml`, `admin-extra*.html`, `_rest_managed.json`, `synonyms.txt`, `stopwords.txt`, `protwords.txt`; keep all field types, including unused ones.
- Schema conversions: `Trie*Field` → `*PointField`, `plong` for `_version_`, remove `<defaultSearchField>` and `<solrQueryParser>`, `WordDelimiterFilterFactory` → Graph variant with fi-admin's own parameters, schema version `1.6`.
- docValues on `string` and Point types (needed for the `status` facet); `string_no_stored` for `stored="false"` string fields so `fl=*` output does not change.
- solrconfig conversions: `luceneMatchVersion` `9.12`, drop removed cache classes and `numVersionBuckets`, add `q.op=AND` to `/select` and `/query`. (`enableStreamBody` was not added in the end; see History.)
- Analyzer jar goes in `<instanceDir>/lib`; portal's `<lib dir="../lib" />` is not copied (to be confirmed in the smoke test).
- Smoke-test inputs on this machine: `iahx/iahx-analyzer/jar/iahx-analyzer-20260119.jar` and the DeCS index in `iahx/iahx-analyzer/resources/decs`; the `solr:9.9` image must be pulled.
- Out of scope: `fi-admin-idx`, the fi-admin Django app, pysolr/haystack compatibility, SolrCloud, managed schema, new fields, relevance changes.
- Risks: token output of portal's chains may differ from the old analyzer classes (`omitPositions` on `decs_keyword` means no phrase queries on `descriptor`/`mh`/`mj`); sorting/faceting on TextField relies on uninversion; a Solr 5 index cannot be opened by Solr 9; the jar and DeCS index on the production Solr 9.9 server are unverified.

## Detailed Plan

<!-- Link to detailed plan file -->

[003-convert-fi-admin-solr-9-config.md](plans/003-convert-fi-admin-solr-9-config.md)

## History

<!-- Keep this updated. Earliest to latest -->
- 2026-11-10: Starting Convert fi-admin Solr config from 5.5 to 9.9 — following plan [003-convert-fi-admin-solr-9-config.md](plans/003-convert-fi-admin-solr-9-config.md)
- 2026-11-10: Converted `schema.xml` and `solrconfig.xml`, removed 8 unreferenced files, added `fi-admin/README.md`. Smoke test on `solr:9.9` (Solr 9.9.0) with `iahx-analyzer-20260119.jar` and the local DeCS index passed: core load, indexing per `django_ct`, AND/`df=tw`, `fq`, facets, sorts, date ranges, DeCS expansion, `/related`, `/terms`, `/export`, `/admin/ping`.
- 2026-11-10: Deviations from the plan found by the smoke test: removed `<jmx/>` (no longer supported), removed `enableRemoteStreaming` and did not add `enableStreamBody` (both ignored by Solr 9; system properties instead), removed the explicit `/export` handler (it shadowed Solr 9's implicit one and returned a plain 10-row search). `portal/conf/solrconfig.xml` has the same three items and was not touched.
- 2026-11-10: Review: found that docValues on the five `indexed="false"` string fields rejected values over 32766 bytes (Solr 5.5 accepted them); set `docValues="false"` on those fields and re-verified on `solr:9.9`. Hyphenated-term queries (`covid-19`, `saude-publica`) checked and working with AND.
