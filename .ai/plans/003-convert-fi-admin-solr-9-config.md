# Plan: Convert fi-admin Solr config from 5.5 to 9.9

## Context

`fi-admin/conf` holds the Solr 5.5 configuration of the `fi-admin` core (Django/Haystack
index of FI-Admin: resources, events, multimedia, legislation, OER, titles, thesaurus,
institutions, bibliographic references). The core must move to Solr 9.9 (Lucene 9.12.2),
where several things this config uses no longer exist: `Trie*Field`,
`<defaultSearchField>`, `<solrQueryParser>`, `FastLRUCache`/`LRUCache`,
`WordDelimiterFilterFactory`, `numVersionBuckets`, and the Lucene 5 build of the DeCS
analyzers. `portal/conf` already runs on Solr 9 in production and is the model.

Spec: `.ai/features/001-fi-admin-solr-9-config-conversion.md`. Decisions already taken
there: portal's `SynonymFilterFactory` chains for DeCS types; compatibility only (no
portal bulk tuning); baseline commit then in-place conversion; remove unreferenced files
but keep all field types; config files only (`fi-admin-idx` untouched); acceptance by a
local `solr:9.9` Docker smoke test.


## Facts established during analysis

- `fi-admin/` is untracked. It now contains 7 files: `schema.xml`, `solrconfig.xml`,
  `currency.xml`, `_rest_managed.json`, `synonyms.txt`, `stopwords.txt`, `protwords.txt`
  (the three empty `admin-extra*.html` are already gone).
- Current branch `main` = `origin/main`; `master` is 34 commits behind. Work branches from `main`.
- `../iahx/iahx-analyzer/jar/iahx-analyzer-20260119.jar` is built against Lucene 9.12.2
  and contains `org.bireme.dia.filters.SynonymFilterFactory`.
- `SynonymFilterFactory` reads the DeCS Lucene index from the `indexPath` parameter,
  default `resources/decs/main`, **relative to the JVM working directory** (in the Solr
  Docker image that is `/opt/solr/server`, to be confirmed in the test).
- A DeCS index exists at `../iahx/iahx-analyzer/resources/decs/main` (14 MB, Lucene 9.12 format).
- Docker, `xmllint`, `curl`, `jq` are available. Only `solr:10` is pulled; `solr:9.9` must be pulled.
- Fields actually used by fi-admin's schema reference these types only: `string`, `int`,
  `long`, `date`, `text`, `decs_keyword`, `decs_code`, `text_with_decs`, `dateiso`,
  `string_lowercase`.

## Files

| File | Action |
| --- | --- |
| `fi-admin/conf/schema.xml` | convert in place |
| `fi-admin/conf/solrconfig.xml` | convert in place |
| `fi-admin/conf/{currency.xml,_rest_managed.json,synonyms.txt,stopwords.txt,protwords.txt}` | delete after baseline commit |
| `fi-admin/README.md` | new: deployment note |
| `.ai/plans/003-convert-fi-admin-solr-9-config.md`, `.ai/current-feature.md` | plan copy + link |

Reference (read only): `portal/conf/schema.xml` lines 1–230 (types), `portal/conf/solrconfig.xml`.

## Steps

### 1. Branch and baseline

- `git switch -c feature/fi-admin-solr-9` from `main`.
- Commit `fi-admin/conf` exactly as it is: "Add fi-admin Solr 5.5 configuration (baseline)".

### 2. Remove unreferenced files

`git rm` the five leftover files. Separate commit.

### 3. `schema.xml`

Keep the file's layout, comments and field order so the diff against the baseline stays readable.

- Header: `<schema name="bvs" version="1.6">`.
- Primitive types:

  | Type | New definition |
  | --- | --- |
  | `string` | `solr.StrField sortMissingLast="true" omitNorms="true" docValues="true"` (portal) |
  | `string_no_stored` (new) | as `string` + `useDocValuesAsStored="false"` (portal) |
  | `boolean` | unchanged |
  | `int`, `tint` | `solr.IntPointField docValues="true"` |
  | `float`, `tfloat` | `solr.FloatPointField docValues="true"` |
  | `long`, `tlong` | `solr.LongPointField docValues="true"` |
  | `plong` (new) | `solr.LongPointField docValues="true"` (portal) |
  | `double`, `tdouble` | `solr.DoublePointField docValues="true"` |
  | `date`, `tdate` | `solr.DatePointField docValues="true"` |
  | `ignored` | add `useDocValuesAsStored="false"` (portal) |

  `precisionStep` and `positionIncrementGap` are dropped from the numeric types.
- DeCS types `decs`, `decs_simple`, `decs_keyword`, `decs_qualifier`,
  `decs_authorized_category`, `text_with_decs`: replace each definition with portal's,
  copied verbatim (tokenizer, `SynonymFilterFactory` parameters, `LengthFilterFactory`,
  `omitPositions`, query analyzers).
- `text`: `WordDelimiterFilterFactory` → `WordDelimiterGraphFilterFactory` in both
  analyzers, same parameters as today; append `solr.FlattenGraphFilterFactory` to the
  index analyzer.
- `textSpell`: same factory swap; add `omitPositions="true"` as portal.
- `text_ws`, `decs_code`, `dateiso`, `string_lowercase`, `string_normalized`,
  `multilanguage`, `textSpellPhrase`: left as they are.
- Fields:
  - `_version_` → `type="plong"`.
  - `media_type_filter`, `media_collection_filter`, `short_title` and
    `<dynamicField name="collection_*">` → `type="string_no_stored"`.
  - Everything else unchanged, including `<dynamicField name="*" type="text">`.
- Delete `<defaultSearchField>` and `<solrQueryParser>`.
- copyFields unchanged.

### 4. `solrconfig.xml`

Keep comments and structure; only these edits:

- `<luceneMatchVersion>9.12</luceneMatchVersion>`.
- `<updateLog>`: remove the `numVersionBuckets` line; keep `dir`.
- `filterCache`, `queryResultCache`, `documentCache`, `perSegFilter`: remove the `class`
  attribute; keep sizes, autowarm and `regenerator`.
- `/select` defaults: add `<str name="q.op">AND</str>` after `df`.
- `/query` defaults: add `<str name="q.op">AND</str>`.
- `<requestParsers>`: add `enableStreamBody="true"`.
- Update stale comments that mention removed features where they sit next to an edited line.
- No `<lib>` directive is added. Nothing else changes (commit settings, `infoStream`,
  `<jmx/>`, `/related`, `/export`, `initParams`, `/analysis/*`, `/debug/dump`, `/terms`, `<admin>`).

### 5. Smoke test (iterate until green)

All test material lives in the session scratchpad, nothing in the repo.

1. Build a core directory: `fi-admin/core.properties` (`name=fi-admin`), `conf/` copied
   from the repo, `lib/iahx-analyzer-20260119.jar`, empty `data/`; copy the DeCS index.
2. `docker pull solr:9.9`, then run a container named `fi-admin-solr9-test` on host port
   8984 with the core dir mounted at `/var/solr/data/fi-admin` and the DeCS index at
   `/opt/solr/server/resources/decs` (read-only). Confirm the JVM cwd via
   `/proc/<pid>/cwd`; adjust the mount if it differs.
3. Check `GET /solr/admin/cores?action=STATUS` shows the core with no `initFailures`, and
   scan `docker logs` for `ERROR` and for `WARN` lines naming deprecated/removed config.
4. Post one small JSON document per `django_ct` family (`main.resource`, `events.event`,
   `multimedia.media`, `title.title`, `leisref.act`, `oer.oer`,
   `thesaurus.identifierdesc`, `institution.institution`, `biblioref.reference`) with
   `status`, dates, descriptors in `^dNNNN` form, a `collection_x` dynamic field and an
   undeclared field (to exercise `*`), then commit.
5. Assertions with `curl` + `jq`:
   - `q=word1 word2` matches only the document containing both (AND, `df=tw`).
   - `fq=(status:1 AND django_ct:main.resource)` and `fq=django_ct:title.title*`.
   - `/select` facet counts present for `status`, `publication_year`,
     `descriptor_filter`, `type`.
   - `sort=title_sort asc` orders case- and accent-insensitively.
   - `/analysis/field` on `descriptor` and `tw` with a known DeCS term shows synonym /
     translation tokens; searching `tw` by a translation finds the document.
   - `descriptor_filter` facet values are bare `^dNNNN` codes.
   - `fl=*` omits `media_type_filter`, `short_title`, `collection_x`, `tw`.
   - `/related?q=id:<x>` and `/terms?terms.fl=tw` answer with status 0.
   - `start_date` range query and sort work.
6. `xmllint --noout fi-admin/conf/*.xml`.
7. Fix whatever Solr rejects and rerun. Known fallbacks: `SortableTextField` for
   `title_sort` if sorting a `TextField` fails; drop `<jmx/>` or the explicit `/export`
   handler if 9.9 refuses them; set `uninvertible="true"` explicitly on TextField facets
   if required.
8. Remove the container when done.

### 6. `fi-admin/README.md`

Short deployment note: target Solr 9.9; analyzer jar in `<instanceDir>/lib`; DeCS index
location (`resources/decs/main` under Solr's working directory, as verified in step 5);
a Solr 5 index cannot be opened, so start with empty `data/` and run a full rebuild;
summary of behavioural differences found (e.g. no phrase queries on `decs_keyword`).

### 7. Commit and record

- Commit the conversion (schema + solrconfig + README) on the feature branch.
- Save this plan to `.ai/plans/003-…`, link it under `## Detailed Plan`, and append the
  smoke-test outcome to `## History` in `.ai/current-feature.md`.
- No push, PR or merge here; those are `/feature pr` and `/feature complete`.

## Verification

Step 5 is the end-to-end check: the core must load on a real Solr 9.9 with the real
analyzer jar and DeCS index, index one document of every type, and pass every assertion
in 5.5. Any assertion that cannot be made to pass is reported with the Solr output rather
than worked around silently.

## Not covered

- Token-for-token comparison against the running Solr 5.5 core (no 5.5 instance with the
  old analyzer jar and DeCS data is set up locally).
- pysolr / django-haystack behaviour against Solr 9, and `fi-admin-idx` deployment.
