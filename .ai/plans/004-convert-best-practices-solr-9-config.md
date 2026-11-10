# Plan: Convert best-practices Solr config from 5.5 to 9.9

## Context

`best-practices/conf` is the Solr 5.5 configuration of the `best-practices` core. It must
move to Solr 9.9 (Lucene 9.12.2). The file set is the same 5.5 template `fi-admin/conf`
started from, and fi-admin was converted and validated in feature 001, so this is a
repeat of that conversion with three differences: its own fields and facets, its own
commit policy, and no use of DeCS analysis.

Spec: `.ai/features/002-best-practices-solr-9-config-conversion.md`. Decisions already
taken: remove the seven unused DeCS field types (the core then needs no custom jar or
DeCS index); otherwise follow fi-admin (compatibility only, baseline commit then in-place
conversion, delete unreferenced files, keep other unused types, config + README only,
local `solr:9.9` smoke test).


## Facts established during analysis

- `best-practices/` is untracked: `schema.xml`, `solrconfig.xml` and eight unreferenced
  files (byte-identical to the ones removed from fi-admin).
- `best-practices/conf/solrconfig.xml` differs from fi-admin's 5.5 baseline (commit
  `8576521`) in exactly two places: commit timing (hard 15 s, soft `-1`) and the
  `/select` `facet.field` list (11 fields). So the final fi-admin `solrconfig.xml` plus
  those two differences is the expected result.
- `schema.xml` type section differs from fi-admin's baseline only by a `TrimFilterFactory`
  absent/commented in `string_lowercase` and `string_normalized`. Fields: 32 + catch-all
  `*`; copyFields `title`, `introduction` → `tw`; `tw` is plain `text`.
- Fields use only `string`, `text`, `int` (`status`, stored-only) and `long` (`_version_`).
- `solr:9.9` image is already pulled. No jar or DeCS index is needed for this core.
- Skill convention: commits carry no Claude co-author line.

## Files

| File | Action |
| --- | --- |
| `best-practices/conf/schema.xml` | convert in place |
| `best-practices/conf/solrconfig.xml` | convert in place |
| `best-practices/conf/{currency.xml,_rest_managed.json,synonyms.txt,stopwords.txt,protwords.txt,admin-extra*.html}` | delete after baseline commit |
| `best-practices/README.md` | new |
| `.ai/plans/004-convert-best-practices-solr-9-config.md`, `.ai/current-feature.md` | plan copy + link |

Reference (read only): `fi-admin/conf/schema.xml`, `fi-admin/conf/solrconfig.xml`,
`fi-admin/README.md`.

## Steps

### 1. Branch and baseline

- `git checkout -b feature/best-practices-solr-9` from `main`.
- Commit `best-practices/conf` exactly as it is: "Add best-practices Solr 5.5 configuration (baseline)".

### 2. Remove unreferenced files

`git rm` the eight files. Separate commit.

### 3. `schema.xml`

Keep layout, comments and field order.

- `version="1.5"` → `1.6`.
- Primitive types block replaced by fi-admin's converted block, minus `string_no_stored`:
  `string` (`docValues="true"`), `boolean`, `int`/`float`/`long`/`plong`/`double`/`tint`/
  `tfloat`/`tlong`/`tdouble` as Point fields with `docValues="true"`, `date`/`tdate` as
  `DatePointField` with `docValues="true"`.
- Delete the `decs`, `decs_simple`, `decs_keyword`, `decs_code`, `decs_qualifier`,
  `decs_authorized_category` and `text_with_decs` field types.
- `text`: `WordDelimiterGraphFilterFactory` in both analyzers (same parameters) and
  `FlattenGraphFilterFactory` at the end of the index analyzer.
- `textSpell`: Graph factory, `omitPositions="true"`.
- `ignored`: add `useDocValuesAsStored="false"`.
- `_version_` → `type="plong"`.
- `status` → add `docValues="false"` (it is `indexed="false" stored="true"` today).
- Delete `<defaultSearchField>` and `<solrQueryParser>`, leaving the same pointer comment
  as fi-admin.
- All other types, fields and copyFields unchanged.

### 4. `solrconfig.xml`

Apply the same edits that produced the final fi-admin file:

- `luceneMatchVersion` → `9.12`.
- Remove `numVersionBuckets` (line and its comment paragraph).
- Remove cache `class` attributes; refresh the cache comment.
- Add `q.op=AND` to `/select` (after `df`) and `/query`.
- Replace the `<jmx/>` block with the "no longer supported" comment.
- Remove `enableRemoteStreaming` from `<requestParsers>`; keep the system-property comment.
- Replace the explicit `/export` handler with the "implicit in Solr 9" comment.

Check: `diff fi-admin/conf/solrconfig.xml best-practices/conf/solrconfig.xml` must show
only the commit-timing lines and the `facet.field` list.

### 5. Smoke test (iterate until green)

Test material in the session scratchpad, fresh directory, nothing in the repo.

1. Core dir with `core.properties` (`name=best-practices`), `conf/` copied from the repo,
   empty `data/`; **no `lib/`, no DeCS mount**. Run `solr:9.9` as
   `best-practices-solr9-test` on host port 8985.
2. Core STATUS has no `initFailures`; `docker logs` shows no ERROR and no core-specific WARN.
3. Index sample documents through JSON and XML updates: every declared field populated,
   multi-valued facet values, accented and hyphenated text, an undeclared field, and a
   value over 32766 bytes in `outcome_information` (`text`, `indexed="false"`).
4. Assertions with `curl` + `jq`:
   - A document added without commit is not found; after an explicit commit it is.
   - `q=word1 word2` is ANDed on `/select` and `/query`; bare terms search `tw`
     (title + introduction only).
   - Accent-insensitive and hyphenated matches (`saude`, `covid-19`).
   - All 11 facet fields return counts; `f.<field>.facet.limit` works.
   - `fq=country:"X"`, `fq=is_private:"false"` and a combined AND filter.
   - `fl=*` returns stored fields including `status`, and not `tw`.
   - Query on an undeclared field (catch-all) and on a declared non-`tw` field (`keywords:x`).
   - Sort on a single-valued string field (`sort=type asc`).
   - `/related`, `/terms`, `/export` (string field), `/admin/ping` answer OK.
   - `/config/updateHandler` reports `autoCommit.maxTime=15000`, `openSearcher=false`,
     `autoSoftCommit.maxTime=-1`; tlog files exist.
5. `xmllint --noout best-practices/conf/*.xml`.
6. Scripted comparison with the baseline schema: no field, dynamic field or copyField
   missing or changed except `_version_` type and `status` `docValues`; only the seven
   DeCS types removed, only `plong` added; no field references an undefined type.
7. Fix anything Solr rejects and rerun. Remove the container at the end.

### 6. `best-practices/README.md`

Modelled on `fi-admin/README.md`: deploying (Solr 9.9, no jar or DeCS index, full reindex,
streaming system properties), what changed in each file, behaviour notes (documents
visible only after an explicit commit, unchanged from 5.5; `/export` needs docValues
fields), validation summary and what was not tested.

### 7. Commit and record

- Commit schema + solrconfig + README on the feature branch (no co-author line).
- Save this plan to `.ai/plans/004-…`, link it under `## Detailed Plan`, append the
  smoke-test outcome to `## History`.
- No push or merge here; that is `/feature complete`.

## Verification

Step 5 on a real Solr 9.9 is the end-to-end check, plus the `diff` in step 4 and the
scripted schema comparison in 5.6. Anything that cannot be made to pass is reported with
the Solr output.

## Not covered

- The client application's real requests (not available on this machine).
- `plugins-idx` deployment and the `relatos-experiencia` core.
