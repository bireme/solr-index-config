# Feature 003: Convert relatos-experiencia Solr config from 5.5 to 9.9

## Summary

Convert `relatos-experiencia/conf/schema.xml` and `relatos-experiencia/conf/solrconfig.xml`,
written for Solr 5.5 (`luceneMatchVersion` 5.4.1), so the `relatos-experiencia` core loads
and behaves the same on Solr 9.9 (Lucene 9.12.2).

The config is the same Solr 5.5 template as `best-practices/conf`. Its `solrconfig.xml`
differs from the best-practices 5.5 baseline (commit `e3e52a9`) **only in the `/select`
facet list**; `schema.xml` differs only in the field list and copyFields. The converted
`best-practices/conf` (feature 002) is the direct model, and its decisions are reused.

## Current state (Solr 5.5)

- `relatos-experiencia/` is untracked. Its `conf/` is byte-identical to the deployed copy
  in `plugins-idx/solr_indexes/relatos-experiencia/conf` (deployed `data/` holds only
  `README.txt`). `conf/` holds `schema.xml`, `solrconfig.xml` and the same eight
  unreferenced files as best-practices (`currency.xml`, `admin-extra.html`,
  `admin-extra.menu-top.html`, `admin-extra.menu-bottom.html`, `_rest_managed.json`,
  `synonyms.txt`, `stopwords.txt`, `protwords.txt`).
- 35 `<field>` entries (including `_version_` and `tw`) + catch-all
  `<dynamicField name="*" type="text">`; 5 copyFields (`title`, `notes`, `description`,
  `fulltext`, `issue` → `tw`). `tw` is plain `text`, not `text_with_decs`.
- Field types actually used: `string`, `text`, `long` (`_version_`). **No field uses a DeCS
  type, and no numeric field other than `_version_` exists.**
- Stored-only (`indexed="false"`) fields:
  - `string`: `start_date`, `end_date`, `partial_date`, `other_date`.
  - `text`: `challenges_information`, `lessons_learned`, `other_medias`, `other_docs`,
    `other_videos`, `related_links`, `products_information`.
- `status` and `other_status` are indexed `string` fields (unlike best-practices, where
  `status` was a stored-only `int`).
- `/select` defaults: `df=tw`, 4 facet fields (`population_group`, `thematic_area`,
  `country`, `collection`), `facet.limit=20`, `facet.mincount=1`.
- Commit policy (same as best-practices): hard commit every 15 s with
  `openSearcher=false`, soft commit disabled (`-1`), updateLog on. New documents become
  visible only on an explicit commit.
- Deployed from `plugins-idx` (image `bireme/solr:5.5.5`, same container as
  best-practices; the health check pings `best-practices`, not this core).
- The client application is not on this machine (`wp-plugins` has no reference to it).

## Decisions (from the spec interview)

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Approach | **Reuse all feature 002 decisions**: remove the 7 unused DeCS field types; compatibility only; baseline commit then in-place conversion on a feature branch; delete the eight unreferenced files; keep the other unused field types; config files + README only (`plugins-idx` untouched); accept with a local stock `solr:9.9` smoke test (no jar, no DeCS index). |
| 2 | Stored-only string fields | `start_date`, `end_date`, `partial_date`, `other_date` get **`docValues="false"`**, so they stay stored-only exactly as in 5.5 and accept values over 32766 bytes (the fi-admin fix). |

## Goals

- The `relatos-experiencia` core starts on a stock Solr 9.9 with no schema/config errors
  and no configuration warnings, **without any custom jar or DeCS index**.
- Every field, the dynamic field and all five copyFields still exist with the same name
  and the same stored/indexed/multiValued semantics.
- Queries behave as before: default field `tw`, default operator AND, the 4 `/select`
  facet fields, `/related`, `/terms`, `/admin/ping`.
- Commit policy unchanged: 15 s hard commit (`openSearcher=false`), soft commit off,
  updateLog on.
- `relatos-experiencia/conf` contains only `schema.xml` and `solrconfig.xml`.
- `relatos-experiencia/README.md` documents deployment and what changed.

## Changes: `schema.xml`

Same as the converted `best-practices/conf/schema.xml`:

1. Version `1.5` → `1.6`.
2. Primitive types: `string` with `docValues="true"`; `Trie*Field` → `*PointField` with
   `docValues="true"`; add `plong` and use it for `_version_`. `string_no_stored` is not
   added (no `stored="false"` string field exists).
3. Remove the seven DeCS field types (`decs`, `decs_simple`, `decs_keyword`, `decs_code`,
   `decs_qualifier`, `decs_authorized_category`, `text_with_decs`).
4. `WordDelimiterFilterFactory` → `WordDelimiterGraphFilterFactory` in `text` and
   `textSpell`, same parameters; `FlattenGraphFilterFactory` appended to the `text` index
   analyzer; `omitPositions="true"` on `textSpell`.
5. `ignored` gains `useDocValuesAsStored="false"`.
6. Other types (`boolean`, `text_ws`, `dateiso`, `string_lowercase`, `string_normalized`,
   `multilanguage`, `textSpellPhrase`) kept unchanged.
7. Remove `<defaultSearchField>` and `<solrQueryParser>`.
8. Fields and copyFields unchanged, except `docValues="false"` on the four stored-only
   date strings (decision 2). The stored-only `text` fields need nothing (`text` has no
   docValues).

## Changes: `solrconfig.xml`

Take the converted `best-practices/conf/solrconfig.xml` edits (equivalently: copy it and
put back relatos-experiencia's facet list):

1. `luceneMatchVersion` → `9.12`.
2. `<updateLog>`: remove `numVersionBuckets`.
3. Caches: remove `class` attributes; sizes unchanged.
4. `/select` and `/query` defaults: add `q.op=AND`.
5. Remove `<jmx/>`.
6. Remove `enableRemoteStreaming` from `<requestParsers>`; do not add `enableStreamBody`.
7. Remove the explicit `/export` handler.
8. Unchanged: commit settings, the 4 facet fields, `/related`, `initParams`,
   `/analysis/*`, `/debug/dump`, `/terms`, `<admin>`, `infoStream`.

Expected result: `diff best-practices/conf/solrconfig.xml relatos-experiencia/conf/solrconfig.xml`
shows only the facet list.

## Files removed

The eight unreferenced files listed under "Current state".

## Deliverable: `relatos-experiencia/README.md`

Same structure as `best-practices/README.md`: target Solr 9.9; no custom jar or DeCS index
needed; a Solr 5 index cannot be opened, so start with empty `data/` and reindex;
streaming system properties if needed; what changed from 5.5; validation summary.

## Acceptance: local smoke test

Throwaway `solr:9.9` container with only the converted conf (no `lib/`, no DeCS mount).

1. Core loads; no ERROR and no core-specific WARN in the log.
2. Sample documents index (JSON and XML) and commit, covering every declared field,
   multi-valued facet fields (`population_group`, `thematic_area`, `collection`), an
   undeclared field (catch-all `*`), a value over 32766 bytes in a stored-only date
   string (`other_date`) and in a stored-only text field.
3. Queries:
   - `q` without field searches `tw` on `/select` (`/query` keeps its 5.5 `df=text`, so
     AND is checked there with an explicit field); two terms are ANDed; terms
     from each of the five copyField sources are found.
   - Hyphenated and accented terms match (`text` analysis).
   - `/select` returns counts for all 4 facet fields.
   - `fq` on facet fields and on `status` (`status:"X"`, now indexed), combined with AND.
   - `fl=*` returns stored fields (including the date strings), not `tw`.
   - `/related`, `/terms`, `/export` (on a string field) and `/admin/ping` answer OK.
   - Documents are not visible before an explicit commit and are after it.
4. `/config` reports `autoCommit.maxTime=15000`, `autoSoftCommit.maxTime=-1`; tlog files exist.
5. `xmllint --noout` passes on both files.
6. Scripted comparison against the baseline: no field, dynamic field or copyField lost or
   changed, apart from `_version_` → `plong` and `docValues="false"` on the four date
   strings.
7. `solrconfig.xml` differs from `best-practices/conf/solrconfig.xml` only in the facet list.

## Out of scope

- `plugins-idx` (still `bireme/solr:5.5.5`; its health check only covers best-practices)
  and the application that feeds/queries the core.
- Tuning, new fields, relevance changes, SolrCloud, managed schema.

## Open items / risks

- **Client query patterns are unknown**: the client is not on this machine, so the smoke
  test uses the patterns implied by the config. Sorting, if the client does it, is not
  confirmed (`title` is tokenized `text`; the date strings are stored-only and cannot be
  sorted or filtered, as in 5.5).
- A full reindex is mandatory when the server moves to Solr 9.
- If a DeCS-expanded field is wanted later, the types can be copied from
  `fi-admin/conf/schema.xml` together with the jar and index.
