# Plan: Convert relatos-experiencia Solr config from 5.5 to 9.9

## Context

`relatos-experiencia/conf` is the Solr 5.5 configuration of the `relatos-experiencia`
core (deployed from `plugins-idx`, same container as best-practices). It must move to
Solr 9.9 (Lucene 9.12.2). It is the same 5.5 template as best-practices, which was
converted and validated in feature 002, so this repeats that conversion.

Spec: `.ai/features/003-relatos-experiencia-solr-9-config-conversion.md`. Decisions taken:
reuse all of 002's decisions (remove the 7 unused DeCS types; compatibility only; baseline
commit then in-place conversion; delete the 8 unreferenced files; config + README only;
stock `solr:9.9` smoke test), and `docValues="false"` on the four stored-only date strings.
No further clarifications needed.

## Facts established during analysis

- `relatos-experiencia/` is untracked; `conf/` is byte-identical to the deployed copy in
  `plugins-idx/solr_indexes/relatos-experiencia/conf`.
- `schema.xml`: everything before `<fields>` (header + all field types) is **identical**
  to the best-practices 5.5 baseline (commit `e3e52a9`); the part after `</fields>` differs
  only in the copyFields (plus one blank line). So the converted header/types block of
  `best-practices/conf/schema.xml` can be reused verbatim.
- Fields: 35 `<field>` entries + catch-all `*`; copyFields `title`, `notes`, `description`,
  `fulltext`, `issue` → `tw`. Types used: `string`, `text`, `long` (`_version_`) only.
  Stored-only strings: `start_date`, `end_date`, `partial_date`, `other_date`.
  `status`/`other_status` are indexed strings.
- `solrconfig.xml` differs from the best-practices 5.5 baseline only in the `/select`
  facet list (`population_group`, `thematic_area`, `country`, `collection`).
- `solr:9.9` image is pulled; host port 8985 is free.
- Convention from previous features: commits carry no Claude co-author line.

## Files

| File | Action |
| --- | --- |
| `relatos-experiencia/conf/schema.xml` | convert in place |
| `relatos-experiencia/conf/solrconfig.xml` | convert in place |
| `relatos-experiencia/conf/{currency.xml,_rest_managed.json,synonyms.txt,stopwords.txt,protwords.txt,admin-extra*.html}` | delete after baseline commit |
| `relatos-experiencia/README.md` | new |
| `.ai/plans/005-convert-relatos-experiencia-solr-9-config.md`, `.ai/current-feature.md` | plan copy + link |

Reference (read only): `best-practices/conf/schema.xml`, `best-practices/conf/solrconfig.xml`,
`best-practices/README.md`, `.ai/logs/2026-11-10-best-practices-solr-9-config-conversion.md`.

## Steps

### 1. Branch and baseline

- `git checkout -b feature/relatos-experiencia-solr-9` from `main`.
- Commit `relatos-experiencia/conf` as is: "Add relatos-experiencia Solr 5.5 configuration (baseline)".

### 2. Remove unreferenced files

`git rm` the eight files. Separate commit.

### 3. `schema.xml`

- Replace everything up to `<fields>` with the converted best-practices header/types
  block (version `1.6`, Point types + `plong`, `string` with docValues, DeCS types removed,
  WordDelimiterGraph + FlattenGraph in `text`, `textSpell` with `omitPositions`, `ignored`
  with `useDocValuesAsStored="false"`).
- Fields: keep order and comments; `_version_` → `type="plong"`; add `docValues="false"`
  to `start_date`, `end_date`, `partial_date`, `other_date`. Nothing else changes.
- After `</fields>`: remove `<defaultSearchField>` and `<solrQueryParser>` with the same
  pointer comment as best-practices; the five copyFields unchanged.

### 4. `solrconfig.xml`

Copy `best-practices/conf/solrconfig.xml` and restore relatos-experiencia's four
`facet.field` lines. Check: `diff best-practices/conf/solrconfig.xml relatos-experiencia/conf/solrconfig.xml`
shows only the facet list.

### 5. Smoke test (iterate until green)

Test material in the session scratchpad. Core dir with `core.properties`
(`name=relatos-experiencia`), the converted `conf/`, empty `data/`; no `lib/`, no DeCS
mount. Container `relatos-experiencia-solr9-test` from `solr:9.9`, host port 8985.

1. Core STATUS has no `initFailures`; `docker logs` has no ERROR and no core-specific WARN.
2. Index through JSON and XML: every declared field, multi-valued facet values, accented
   and hyphenated text, an undeclared field, a value over 32766 bytes in `other_date`
   (stored-only string) and in `lessons_learned` (stored-only text).
3. Assertions with `curl` + `jq`:
   - Uncommitted document invisible; visible after explicit commit.
   - `q=word1 word2` ANDed on `/select` and `/query`; a unique term placed in each of
     `title`, `notes`, `description`, `fulltext`, `issue` is found by a bare query; a term
     only in a non-copied field (e.g. `objectives`) is not.
   - Accent-insensitive and hyphenated matches (`saude`, `covid-19`).
   - All 4 facet fields return counts.
   - `fq=status:"X"`, `fq=country:"X"`, `fq=thematic_area:"X"`, combined AND.
   - `fl=*` returns stored fields (including the date strings and the 32 KB values), not `tw`.
   - Catch-all field query; declared non-`tw` field query (`keywords:x`, `objectives:x`).
   - Sort on a single-valued string (`sort=country asc`).
   - `/related`, `/terms`, `/export` (string field), `/admin/ping` OK.
   - `/config/updateHandler`: `autoCommit.maxTime=15000`, `openSearcher=false`,
     `autoSoftCommit.maxTime=-1`; tlog files exist.
4. `xmllint --noout relatos-experiencia/conf/*.xml`.
5. Scripted comparison with the baseline schema: no field, dynamic field or copyField
   lost or changed except `_version_` type and the four `docValues="false"`; only the
   seven DeCS types removed and `plong` added; no field references an undefined type.
6. Fix and rerun as needed; remove the container at the end.

### 6. `relatos-experiencia/README.md`

Modelled on `best-practices/README.md`: deploying (Solr 9.9, no jar or DeCS index, full
reindex, streaming system properties), what changed per file, behaviour notes (explicit
commits required; date strings stored-only; `title` not alphabetically sortable;
`/export` needs docValues fields), validation summary and what was not tested.

### 7. Commit and record

- Commit schema + solrconfig + README on the feature branch (no co-author line).
- Save this plan to `.ai/plans/005-convert-relatos-experiencia-solr-9-config.md`, link it
  under `## Detailed Plan`, append the smoke-test outcome to `## History`.
- No push or merge here; that is `/feature complete`.

## Verification

Step 5 on a real Solr 9.9 is the end-to-end check, plus the `diff` in step 4 and the
scripted schema comparison in 5.5.

## Not covered

- The client application's real requests (not available on this machine).
- `plugins-idx` deployment (still `bireme/solr:5.5.5`).
