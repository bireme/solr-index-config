# Feature 002: Convert best-practices Solr config from 5.5 to 9.9

## Summary

Convert `best-practices/conf/schema.xml` and `best-practices/conf/solrconfig.xml`, written
for Solr 5.5 (`luceneMatchVersion` 5.4.1), so the `best-practices` core loads and behaves
the same on Solr 9.9 (Lucene 9.12.2).

The config is the same Solr 5.5 template that `fi-admin/conf` started from, with its own
field list, facets and commit policy. The converted `fi-admin/conf` (feature 001) is the
direct model; its smoke-test findings are applied here from the start. See
`.ai/logs/2026-11-10-fi-admin-solr-9-config-conversion.md`.

## Current state (Solr 5.5)

- `best-practices/` is untracked. `conf/` holds `schema.xml`, `solrconfig.xml` and eight
  files nothing references (`currency.xml`, `admin-extra.html`,
  `admin-extra.menu-top.html`, `admin-extra.menu-bottom.html`, `_rest_managed.json`,
  `synonyms.txt`, `stopwords.txt`, `protwords.txt`), byte-identical to fi-admin's.
- 32 fields + catch-all `<dynamicField name="*" type="text">`; 2 copyFields
  (`title`, `introduction` → `tw`). `tw` is plain `text`, not `text_with_decs`.
- Field types actually used: `string`, `text`, `int`, `long`. **No field uses a DeCS type.**
- `/select` defaults: `df=tw`, 11 facet fields (`country`, `subregion`, `target`, `type`,
  `intervention`, `population_group`, `institution`, `stakeholder`, `outcomes`, `call`,
  `is_private`), `facet.limit=20`, `facet.mincount=1`.
- Commit policy: hard commit every 15 s with `openSearcher=false`, soft commit disabled
  (`-1`), updateLog on. New documents become visible only on an explicit commit.
- Deployed from the separate `plugins-idx` repo (image `bireme/solr:5.5.5`, health check on
  `/solr/best-practices/admin/ping`).

## Decisions (from the spec interview)

| # | Topic | Decision |
| --- | --- | --- |
| 1 | DeCS field types | **Remove** `decs`, `decs_simple`, `decs_keyword`, `decs_code`, `decs_qualifier`, `decs_authorized_category`, `text_with_decs`. No field uses them, and keeping them would make the core depend on the `iahx-analyzer` jar and a DeCS index. |
| 2 | Everything else | Same as fi-admin: compatibility only; baseline commit then in-place conversion on a feature branch; delete the eight unreferenced files; keep the other unused field types; config files + README only (`plugins-idx` untouched); accept with a local `solr:9.9` smoke test. |

## Goals

- The `best-practices` core starts on a stock Solr 9.9 with no schema/config errors and no
  configuration warnings, **without any custom jar or DeCS index**.
- Every field, the dynamic field and both copyFields still exist with the same name and
  the same stored/indexed/multiValued semantics.
- Queries behave as before: default field `tw`, default operator AND, the `/select` facet
  list, `/related`, `/terms`, `/admin/ping`.
- Commit policy unchanged: 15 s hard commit (`openSearcher=false`), soft commit off,
  updateLog on.
- `best-practices/conf` contains only `schema.xml` and `solrconfig.xml`.
- `best-practices/README.md` documents deployment and what changed.

## Changes: `schema.xml`

1. Version `1.5` → `1.6`.
2. Primitive types as in converted fi-admin: `string` with `docValues="true"`;
   `Trie*Field` → `*PointField` with `docValues="true"`; add `plong` and use it for
   `_version_`. `string_no_stored` is **not** added: no `stored="false"` string field exists.
3. Remove the seven DeCS field types (decision 1).
4. `WordDelimiterFilterFactory` → `WordDelimiterGraphFilterFactory` in `text` and
   `textSpell`, same parameters; `FlattenGraphFilterFactory` appended to the `text` index
   analyzer; `omitPositions="true"` on `textSpell`.
5. `ignored` gains `useDocValuesAsStored="false"`.
6. Other types (`boolean`, `text_ws`, `dateiso`, `string_lowercase`, `string_normalized`,
   `multilanguage`, `textSpellPhrase`) kept unchanged.
7. Remove `<defaultSearchField>` and `<solrQueryParser>`.
8. Fields and copyFields unchanged. `status` (`int`, `indexed="false" stored="true"`) gets
   `docValues="false"` so it stays a returned-only value as today. There are no
   `indexed="false"` string fields, so the fi-admin 32766-byte docValues fix has nothing
   to apply to here (the `indexed="false"` fields are `text`, which has no docValues).

## Changes: `solrconfig.xml`

Identical edits to the final fi-admin `solrconfig.xml`:

1. `luceneMatchVersion` → `9.12`.
2. `<updateLog>`: remove `numVersionBuckets`.
3. Caches: remove `class` attributes; sizes unchanged.
4. `/select` and `/query` defaults: add `q.op=AND`.
5. Remove `<jmx/>` (unsupported in Solr 9).
6. Remove `enableRemoteStreaming` from `<requestParsers>` (ignored in Solr 9); do not add
   `enableStreamBody`.
7. Remove the explicit `/export` handler (it shadows Solr 9's implicit one and degrades to
   a plain search).
8. Unchanged: commit settings, the 11 facet fields, `/related`, `initParams`,
   `/analysis/*`, `/debug/dump`, `/terms`, `<admin>`, `infoStream`.

## Files removed

The eight unreferenced files listed under "Current state".

## Deliverable: `best-practices/README.md`

Target Solr 9.9; no custom jar or DeCS index needed; a Solr 5 index cannot be opened, so
start with empty `data/` and reindex; streaming system properties if needed; what changed
from 5.5; validation summary.

## Acceptance: local smoke test

Throwaway `solr:9.9` container with only the converted conf (no `lib/`, no DeCS mount).

1. Core loads; no ERROR and no core-specific WARN in the log.
2. Sample documents index (JSON and XML) and commit, covering every declared field, a
   multi-valued facet field, an undeclared field (catch-all `*`), and a text value over
   32766 bytes in an `indexed="false"` text field.
3. Queries:
   - `q` without field searches `tw`; two terms are ANDed (`/select` and `/query`).
   - Hyphenated and accented terms match (`text` analysis).
   - `/select` returns counts for all 11 facet fields, including `is_private`.
   - `fq` on facet fields (`country:"X"`, `is_private:"false"`), combined with AND.
   - `fl=*` returns stored fields, not `tw`; `status` is returned.
   - `/related`, `/terms`, `/export` (on a string field) and `/admin/ping` answer OK.
   - Documents are not visible before an explicit commit (soft commit off) and are after it.
4. `/config` reports `autoCommit.maxTime=15000`, `autoSoftCommit.maxTime=-1`; tlog files exist.
5. `xmllint --noout` passes on both files.
6. Scripted comparison against the baseline: no field, dynamic field or copyField lost or
   changed, apart from `_version_` → `plong` and `status` `docValues="false"`.

## Out of scope

- `plugins-idx` (still `bireme/solr:5.5.5`) and the application that feeds/queries the core.
- The other core in `plugins-idx` (`relatos-experiencia`).
- Tuning, new fields, relevance changes, SolrCloud, managed schema.

## Open items / risks

- **Client query patterns are unknown**: the application that queries this core is not on
  this machine, so the smoke test uses the patterns implied by the config (facets, `df`,
  AND) rather than real requests. Sorting on a specific field, if the client does it, is
  not confirmed.
- A full reindex is mandatory when the server moves to Solr 9.
- Unlike fi-admin, the DeCS types are gone. If a DeCS-expanded field is wanted later, the
  types can be copied from `fi-admin/conf/schema.xml` together with the jar and index.
