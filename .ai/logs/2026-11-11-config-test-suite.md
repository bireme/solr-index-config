# 2026-11-11 — Regression test suite for the Solr core configurations

Spec: `.ai/features/004-config-test-suite.md`
Plan: `.ai/plans/006-config-test-suite.md`
Usage: root `README.md`, section "Testing"

## What was done

- `tests/run.py`: entry point. Standard library only; needs Docker for the live checks.
  Options: core names, `--changed`, `--ref`, `--strict`, `--image` / `SOLR_IMAGE`,
  `--static-only`, `--fast`, `--keep`, `-v`. Exit codes: 0 passed, 1 failures,
  2 environment or usage error.
- `tests/lib/config.py`: parses `schema.xml` and `solrconfig.xml` into a plain model
  (field types and their analysis classes, fields, dynamicFields, copyFields, uniqueKey,
  handler defaults/invariants/appends, initParams, commit settings, caches, legacy items).
- `tests/lib/gitref.py`: model of a core at a git ref (default `origin/main`, then
  `main`) and a readable `+`/`-`/`~` diff; `--changed` core selection (all cores if
  `tests/` changed).
- `tests/lib/solr.py`: one throwaway container for all selected cores, `conf/` mounted
  read-only and copied inside, random localhost port, removed at the end unless `--keep`.
  The analyzer jar goes to `<instanceDir>/lib/` and the DeCS index to
  `/opt/solr/server/resources/decs/main` for the cores whose schema uses
  `org.bireme` classes. Adds `--user-managed` when the image supports it (Solr 10).
- `tests/lib/base.py`: test classes run in the order Static, Load, Visibility, Generic,
  Specific.
  - `Static`: well-formed XML, references resolve (types, copyFields, handler `df` and
    `facet.field`), uniqueKey sane, `/select` has a `df`, and one test per Solr 9
    removal (Trie, WordDelimiterFilter, legacy schema elements, LRU caches, `<jmx/>`,
    `enableRemoteStreaming`, `numVersionBuckets`, `<lib/>`, explicit `/export`).
  - `Load`: the core loads; no WARN/ERROR for the core in the log apart from known ones.
  - `Visibility`: one shared 20 s wait; a document is invisible without commit and
    visible after an explicit commit (cores with soft commit off and `openSearcher=false`).
  - `Generic`: derived from the config: JSON + XML updates, default field and operator,
    `/select` facets, `fl=*`, `/export` returns everything, `/terms`, ping, every search
    handler answers, commit settings and `luceneMatchVersion` as in the file, tlog written.
- `tests/lib/known_issues.py`: expected failures and tolerated log warnings, each with a
  reason. An entry that starts passing, or a log warning no longer printed, fails the run.
- `tests/cores/test_<core>.py` and `tests/fixtures/<core>/docs.json`: core-specific
  checks ported from the 2026-11-10 conversions — relatos-experiencia's 42-check smoke
  script, best-practices and fi-admin rebuilt from their logs and reviews (DeCS
  expansion from `^d8569`, 31 facets, sorts, dates, long stored-only values, etc.).
  `portal` and `api-metrics` have generic checks only.
- Root `README.md` (new) with the core table and the Testing section; pointers from the
  fi-admin, best-practices and relatos-experiencia READMEs. Corrected the `/query` note
  in `best-practices/README.md` (its `df` is `text`).

## Results (`solr:9.9`, Solr 9.9.0, analyzer jar and DeCS index present)

243 tests, exit 0, about 30 s with the image cached.

| Core | Passed | Skipped | Known issues |
| --- | --- | --- | --- |
| api-metrics | 22 | 0 | 8 |
| best-practices | 55 | 0 | 0 |
| fi-admin | 57 | 1 | 0 |
| portal | 23 | 2 | 5 |
| relatos-experiencia | 70 | 0 | 0 |

Skips: fi-admin opens a searcher on hard commit (visibility check not applicable);
portal has no `/select` facets and its `<updateLog>` is commented out.

Verification: five deliberate mutations were caught and reverted (removed copyField,
`q.op` OR, undefined field type, docValues on a stored-only string, removed known-issue
entry); missing jar skips fi-admin/portal live checks with exit 0; no Docker gives
exit 2 while `--static-only` still works; `--changed` selects only touched cores; no
container or files left behind.

## Found in portal and api-metrics (recorded, not fixed)

- Both: explicit `/export` handler (answers as a 10-row search), `<jmx/>`,
  `enableRemoteStreaming`.
- portal: `<lib dir="../lib"/>` ignored (disabled by default since Solr 9.8),
  `enableStreamBody` ignored, warning for the 4096-dimension `vector` field, no
  transaction log (`<updateLog>` commented out: no real-time get or atomic updates).
- api-metrics: Trie field types, `WordDelimiterFilterFactory`, `<solrQueryParser>`,
  `numVersionBuckets` (all load with warnings); `/select` has no `q.op`, so OR.
- The legacy cache classes in both files are inside comments; the active caches use the
  default implementation.

## Deviations from the plan

- Solr 10 needs `--user-managed` to start standalone cores; added to the harness.
- The core-specific suites went in the same commit as the framework.
- `.ai/features/004-assets/` (relatos-experiencia script and surviving fixtures) was
  removed after the port; the checks live in `tests/`.

## On `solr:10` (informative)

best-practices and relatos-experiencia pass except `wt=php` / `phps` (HTTP 400 on
Solr 10); api-metrics loads but its known-warning list differs.

## Open

- `initParams` `df` is not covered by the static reference check nor shown in the git-ref
  diff (all cores' `df=text` resolve today).
- A failing `docker run` (e.g. image pull) ends in a traceback rather than a message.
- portal and api-metrics have no core-specific checks yet; their known issues are not fixed.
