# 2026-11-10 — fi-admin Solr config converted from 5.5 to 9.9

Spec: `.ai/features/001-fi-admin-solr-9-config-conversion.md`
Plan: `.ai/plans/003-convert-fi-admin-solr-9-config.md`
Deployment notes: `fi-admin/README.md`

## What was done

- Added `fi-admin/conf` to the repository as it was on Solr 5.5 (baseline commit), then
  converted it in place using `portal/conf` as the Solr 9 model.
- Removed eight files nothing referenced: `currency.xml`, `admin-extra.html`,
  `admin-extra.menu-top.html`, `admin-extra.menu-bottom.html`, `_rest_managed.json`,
  `synonyms.txt`, `stopwords.txt`, `protwords.txt`.

### schema.xml

- Version `1.5` → `1.6`.
- `Trie*Field` → `*PointField` with docValues; new `plong` type for `_version_`.
- `string` gained docValues; new `string_no_stored` (`useDocValuesAsStored="false"`) for
  `media_type_filter`, `media_collection_filter`, `short_title`, `collection_*`.
- `docValues="false"` on the stored-only string fields `link`, `english_title`,
  `reference_source`, `time_period_textual`, `contact_email`.
- DeCS types (`decs`, `decs_simple`, `decs_keyword`, `decs_qualifier`,
  `decs_authorized_category`, `text_with_decs`) now use portal's
  `org.bireme.dia.filters.SynonymFilterFactory` chains instead of the
  `org.bireme.dia.analysis.*Analyzer` classes.
- `WordDelimiterFilterFactory` → `WordDelimiterGraphFilterFactory` (same parameters) in
  `text` and `textSpell`; `FlattenGraphFilterFactory` added to the `text` index analyzer.
- `<defaultSearchField>` and `<solrQueryParser>` removed.
- All 117 fields, dynamic fields and copyFields kept.

### solrconfig.xml

- `luceneMatchVersion` `5.4.1` → `9.12`.
- `q.op=AND` added to `/select` and `/query` (replaces `solrQueryParser`).
- Cache `class` attributes removed (Caffeine default); sizes unchanged.
- Removed `numVersionBuckets`, `<jmx/>`, `enableRemoteStreaming` and the explicit
  `/export` handler.
- Commit policy unchanged: hard commit 10 min (`openSearcher=false`), soft commit 60 s,
  updateLog on.

## Findings from the Solr 9.9 smoke test

Environment: `solr:9.9` Docker image (Solr 9.9.0), `iahx-analyzer-20260119.jar` in
`<instanceDir>/lib`, DeCS Lucene 9.12 index mounted at
`/opt/solr/server/resources/decs/main`.

1. **Explicit `/export` silently degrades.** The Solr 5 definition (`{!xport}` +
   `wt=xsort`) loads on Solr 9 but shadows the implicit export handler and answers as a
   normal search limited to `rows` (10 of 12 documents returned). Removing it restored
   full export. `portal/conf/solrconfig.xml` still has this definition.
2. **`<jmx/>` is no longer supported** and **`enableRemoteStreaming` / `enableStreamBody`
   are ignored** in `solrconfig.xml`; Solr logs a warning for each. The streaming options
   are system properties now (`-Dsolr.enableRemoteStreaming=true`,
   `-Dsolr.enableStreamBody=true`). Portal has these three items as well.
3. **docValues limit on stored-only strings.** With docValues on the `string` type, a
   value over 32766 bytes in an `indexed="false"` field was rejected
   (`DocValuesField "english_title" is too large`). Solr 5.5 accepted any length there.
   Fixed with per-field `docValues="false"`.
4. **DeCS index path** is `resources/decs/main` relative to the JVM working directory,
   which is `<solr>/server`. The filter's `indexPath` parameter can override it.
5. **`tw` expands only precoded descriptors** (`^dNNNN`, `^dNNNN^sNNNN`), because
   portal's `text_with_decs` chain sets `acceptOnlyPrecoded="true"`. Plain terms are
   expanded in `descriptor`, `mh`, `mj`.
6. Sorting on `title_sort` and faceting on `publication_year` / `descriptor_filter`
   (TextField, no docValues) work through uninversion. `/export` cannot use those fields.

## Checks that passed

Core load without errors or config warnings; JSON and XML updates; one document per
`django_ct` family; default field and AND semantics on `/select` and `/query`; `fq` on
`status` / `django_ct` including wildcards; all 31 `/select` facets; per-field
`facet.limit`; sort on `title_sort`, `status`, `start_date`; date range; DeCS expansion by
translation, synonym and category code; hyphenated terms (`covid-19`, `saude-publica`);
catch-all and `collection_*` dynamic fields; `fl=*` hides `stored="false"` fields;
`/related`, `/terms`, `/export`, `/admin/ping`; `xmllint` on both files.

## Not verified

- Token-for-token parity with the running Solr 5.5 core.
- FI-Admin (pysolr / django-haystack) against Solr 9.
- The analyzer jar and DeCS index on the production Solr 9.9 server.
- `fi-admin-idx` (still `bireme/solr:5.5.5`) was not changed; a full reindex is required
  when it moves to Solr 9.

## Follow-up worth considering

- Apply findings 1 and 2 to `portal/conf/solrconfig.xml`.
