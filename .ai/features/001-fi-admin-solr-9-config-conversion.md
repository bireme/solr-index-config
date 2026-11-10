# Feature 001: Convert fi-admin Solr config from 5.5 to 9.9

## Summary

Convert `fi-admin/conf/schema.xml` and `fi-admin/conf/solrconfig.xml`, written for Solr 5.5
(`luceneMatchVersion` 5.4.1), so the `fi-admin` core loads and behaves the same on Solr 9.9
(Lucene 9.12.2). `portal/conf` is the validated Solr 9 model for syntax, field-type classes
and DeCS analysis chains. fi-admin's own behaviour (commit policy, facets, fields) is kept.

## Decisions (from the spec interview)

| # | Topic | Decision |
| --- | --- | --- |
| 1 | DeCS field types | Replace `org.bireme.dia.analysis.*Analyzer` classes with portal's tokenizer + `org.bireme.dia.filters.SynonymFilterFactory` chains. |
| 2 | solrconfig scope | Compatibility only. Portal's bulk-indexing tuning (`ramBufferSizeMB`, merge policy/scheduler, `autoCommit maxDocs`, soft commit off, `/update` invariants) and its `process-specific-clusters` chain are **not** copied. |
| 3 | File layout | Commit `fi-admin/conf` as-is first (5.5 baseline), then convert in place on a feature branch. |
| 4 | Cleanup | Delete unreferenced files; keep every field type (converted), including unused ones. |
| 5 | Deployment | Config files only. `fi-admin-idx` (image `bireme/solr:5.5.5`) is not modified; a deployment note is delivered instead. |
| 6 | Acceptance | Local Solr 9.9 Docker smoke test: core load, sample indexing, fi-admin query patterns. |

## Goals

- The `fi-admin` core starts on Solr 9.9 with no schema/config errors.
- Every field, dynamic field and copyField of the 5.5 schema still exists with the same
  name, stored/indexed/multiValued semantics.
- fi-admin's queries keep working unchanged: default field `tw`, default operator AND,
  the `/select` facet list, `fq` on `status` / `django_ct`, sort on `title_sort`, `/related`.
- Incremental indexing from Django/Haystack keeps its timing: hard commit 10 min
  (`openSearcher=false`), soft commit 60 s, updateLog enabled.
- `fi-admin/conf` contains only `schema.xml` and `solrconfig.xml`, like `portal/conf`.

## Changes: `schema.xml`

1. **Numeric/date types** — `Trie*Field` was removed in Solr 9. Use portal's definitions:
   `int`/`tint` → `IntPointField`, `float`/`tfloat` → `FloatPointField`,
   `long`/`tlong` → `LongPointField`, `double`/`tdouble` → `DoublePointField`,
   `date`/`tdate` → `DatePointField`. Drop `precisionStep` and `positionIncrementGap`.
   Add `plong` (`LongPointField`, `docValues="true"`) and use it for `_version_`.
2. **docValues** — Point fields cannot be faceted or sorted without docValues, and `status`
   (`int`) is a `/select` facet. Set `docValues="true"` on `string` (as portal) and on the
   Point types. Add portal's `string_no_stored` (`useDocValuesAsStored="false"`) and use it
   for the `string` fields declared `stored="false"` (`media_type_filter`,
   `media_collection_filter`, `short_title`, `collection_*`) so `fl=*` output does not change.
3. **Schema version** — `1.5` → `1.6`. Defaults stay explicit rather than relying on the
   1.7 "docValues everywhere" defaults. (Portal declares `2.0`; not copied.)
4. **Removed elements** — delete `<defaultSearchField>` and `<solrQueryParser>`; both fail
   on Solr 9. Their effect moves to `df` / `q.op` in solrconfig (see below).
5. **WordDelimiter** — `WordDelimiterFilterFactory` → `WordDelimiterGraphFilterFactory` in
   `text` and `textSpell`, keeping fi-admin's own parameters (`catenateWords=1`,
   `catenateNumbers=1`, `catenateAll=0`, `preserveOriginal=1`). Add
   `FlattenGraphFilterFactory` as the last filter of the `text` index analyzer.
6. **DeCS types** — copy portal's definitions verbatim for `decs`, `decs_simple`,
   `decs_keyword`, `decs_qualifier`, `decs_authorized_category` and `text_with_decs`
   (including `omitPositions` and the `LengthFilterFactory` where portal has them).
7. **Unchanged types** — `text_ws`, `decs_code`, `dateiso`, `string_lowercase`,
   `string_normalized`, `multilanguage`, `textSpellPhrase`, `ignored`, `boolean` use only
   factories that still exist in Lucene 9; keep them (align attributes with portal where
   the type exists there).
8. **Fields / copyFields** — unchanged, apart from the type swaps in items 1–2. The
   catch-all `<dynamicField name="*" type="text" …>` stays.

## Changes: `solrconfig.xml`

1. `luceneMatchVersion` `5.4.1` → `9.12`.
2. `<updateLog>`: keep, remove `numVersionBuckets` (no longer supported).
3. Caches: drop `class="solr.FastLRUCache"` / `solr.LRUCache` / `solr.search.LRUCache`
   (removed; Caffeine is the default). Sizes and autowarm counts unchanged.
4. `/select` defaults: add `<str name="q.op">AND</str>` (replaces `solrQueryParser`);
   `df=tw` already present. Facet field list, `facet.limit=20`, `facet.mincount=1` unchanged.
5. `/query` defaults: add `q.op=AND` so the old global default operator still applies.
6. `requestParsers`: add `enableStreamBody="true"` as portal does (it was implicitly on in 5.5).
7. Everything else is already valid on Solr 9 and matches portal's structure: `dataDir`,
   `directoryFactory`, `codecFactory`, `ClassicIndexSchemaFactory`, `lockType`, commit
   settings, `/related`, `/export`, both `initParams`-style defaults, `/analysis/*`,
   `/debug/dump`, `/terms`, `<admin>`, `<jmx/>`. Keep as is; remove an element only if the
   smoke test shows Solr 9.9 rejecting it.

## Files removed

`currency.xml`, `admin-extra.html`, `admin-extra.menu-top.html`,
`admin-extra.menu-bottom.html`, `_rest_managed.json`, `synonyms.txt`, `stopwords.txt`,
`protwords.txt` — nothing in the schema or config references them.

## Deployment note (deliverable, not executed)

Add `fi-admin/README.md` covering:

- Solr 9.9 image/installation replaces `bireme/solr:5.5.5`.
- The analyzer jar (`iahx-analyzer`, the Lucene 9.12.2 build) goes in `<instanceDir>/lib`,
  which Solr loads automatically. Portal's `<lib dir="../lib" />` is not copied: `<lib>`
  directives are disabled by default from Solr 9.8.
- The DeCS Lucene index must be reachable at `resources/decs/main` relative to Solr's
  working directory (path hard-coded as the analyzer default).
- A Solr 5 index cannot be opened by Solr 9: start with an empty `data/` and run a full
  rebuild from fi-admin.

## Acceptance: local smoke test

Throwaway `solr:9.9` container, core `fi-admin`, converted conf,
`iahx/iahx-analyzer/jar/iahx-analyzer-20260119.jar`, DeCS index from
`iahx/iahx-analyzer/resources/decs`.

1. Core loads; Solr log has no ERROR and no schema/config WARN that names a removed feature.
2. Sample documents index and commit for each `django_ct` family (`main.resource`,
   `events.event`, `multimedia.media`, `title.title`, `leisref.act`, `oer.oer`,
   `thesaurus.identifierdesc`, `institution.institution`, bibliographic reference).
3. Queries return the expected documents:
   - `q` without field hits `tw`; two terms are ANDed.
   - `fq=(status:1 AND django_ct:main.resource)` and the wildcard form `django_ct:title.title*`.
   - `/select` returns facet counts for `status`, `publication_year`, `descriptor_filter`
     and at least one string facet.
   - `sort=title_sort asc` works.
   - A DeCS descriptor indexed in `descriptor` / `mh` is found through a synonym or
     translation in `tw`, and `descriptor_filter` holds the `^dNNNN` code.
   - `/related` (MoreLikeThis) answers without error.
   - `fl=*` does not return fields declared `stored="false"`.
4. `xmllint --noout` passes on both files.

## Out of scope

- Changes to `fi-admin-idx` or to the fi-admin Django application.
- Portal's indexing-performance tuning and cluster update chain.
- pysolr / django-haystack compatibility with Solr 9 on the application side.
- SolrCloud, managed schema, new fields or relevance changes.

## Open items / risks

- **Analysis parity**: portal's filter chains replace the monolithic analyzer classes. The
  new jar still ships the classes, but token output may differ in detail (e.g. the
  `LengthFilter` 1–100, `omitPositions` on `decs_keyword` means no phrase queries on
  `descriptor`/`mh`/`mj`). The smoke test covers the common cases only.
- **Sorting/faceting on TextField** (`title_sort`, `publication_year`, `descriptor_filter`)
  depends on uninversion, which Solr 9 still allows; confirmed by the smoke test, with
  `SortableTextField` as the fallback for `title_sort`.
- **`infoStream=true`** is kept from the 5.5 config; it is verbose and portal turns it off.
- **Which jar and DeCS index the production Solr 9.9 server has** is unverified.
- The `solr:9.9` Docker image is not present locally and must be pulled.
