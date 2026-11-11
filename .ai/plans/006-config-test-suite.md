# Plan: Regression test suite for the Solr core configurations

## Context

The three 5.5 → 9.9 conversions were validated with smoke tests written in session
scratch space and never committed. This feature puts a repeatable suite in the repo, to
run whenever a `*/conf/schema.xml` or `*/conf/solrconfig.xml` changes.

Spec: `.ai/features/004-config-test-suite.md`. Decisions already taken: all five cores;
Python 3 standard library only; `IAHX_JAR` / `DECS_INDEX` env vars with skip when missing;
comparison with a git ref (default `origin/main`); `solr:9.9` by default, overridable;
manual runs with `--changed`; core-specific suites for the three converted cores, generic
checks for `portal` and `api-metrics`; known gaps as expected failures.

Decided in this planning step:
- **Git-ref differences are report-only**; `--strict` turns any difference into a failure.
- The uncommitted `best-practices/README.md` `/query` fix becomes the **first commit of the
  feature branch**, on its own.

## Facts established during analysis

- **More test material survives than the spec says.** The earlier session's scratchpad
  (`/tmp/claude-1000/-data-vinicius-dropbox-Projects-bireme-solr-index-config/e020b24e-a248-42f3-af2b-931d210177dd/scratchpad/`)
  still has `docs.json` (fi-admin, 12 documents, one per `django_ct` family, descriptors
  `^d8569` and `^d8569^s22016`) and `bp-docs.json` (best-practices, 3 documents incl. the
  48,000-character value). The assertion scripts for those two cores are gone; their
  checks are listed in `.ai/logs/2026-11-10-{fi-admin,best-practices}-…md` and plan 003 §5.
  `/tmp` is volatile: **copy both files into the repo as the very first action.**
- relatos-experiencia: script preserved at `.ai/features/004-assets/relatos-experiencia-smoke.sh`.
- **DeCS index default corrects the spec:** the index used for fi-admin was the Lucene 9.12
  one at `../iahx/iahx-analyzer/resources/decs/main`; `../docker-repo/solr9/resources/decs/main`
  is an older (`Lucene90`) build. Default `DECS_INDEX` = the iahx one. Jar default:
  `../iahx/iahx-analyzer/jar/iahx-analyzer-20260119.jar`.
- Commit policies differ, so visibility checks must be derived from each config:
  best-practices / relatos-experiencia / api-metrics: hard 15 s `openSearcher=false`, soft off;
  fi-admin: hard 600 s, soft 60 s; portal: hard by `maxDocs`, soft off.
- `portal` and `api-metrics` have never been loaded in a test here. `api-metrics/conf/schema.xml`
  still uses `Trie*Field` types and both still use `solr.LRUCache`/`FastLRUCache`, `<jmx/>`,
  `enableRemoteStreaming` and the explicit `/export`; `portal` has `<lib dir="../lib"/>`
  and a 4096-dimension `knn_vector` field. Their real behaviour on `solr:9.9` is
  **unknown until step 3**; whatever fails there is recorded as a known issue, not fixed.
- Solr log lines carry the core in MDC (`[c: s: r: x:<core> t:]`), which gives a precise
  "core-specific WARN/ERROR" filter; lines without a core are ignored unless ERROR.
- `origin/main` resolves locally. Python is 3.14; code must stay compatible with 3.9+.
- Convention: commits carry no Claude co-author line.

## Layout

```
README.md                      new, short: cores table + "Testing" section
tests/
  run.py                       CLI entry point
  lib/__init__.py
  lib/config.py                parse schema.xml / solrconfig.xml into a plain model
  lib/gitref.py                load the model at a git ref, diff two models, changed cores
  lib/solr.py                  container lifecycle + small HTTP client
  lib/base.py                  StaticChecks, CommitVisibility, GenericLive base TestCases
  lib/known_issues.py          per-core expected failures, each with a reason
  cores/test_<core>.py         one module per core (5)
  fixtures/<core>/docs.json    hand-written documents (+ docs.xml where XML update is tested)
```

No changes to any `*/conf/` file.

## Design

### `lib/config.py`
`load(core_dir | (schema_text, solrconfig_text))` → dict with: `fields`
(name → attributes), `dynamic_fields`, `copy_fields`, `types` (name → class + attributes
+ analyzer class names), `unique_key`, `lucene_match_version`, `handlers` (name → class,
defaults/invariants incl. `df`, `q.op`, `facet.field` list), `auto_commit`,
`auto_soft_commit` (with `${prop:default}` resolved to the default), `caches`, plus flags
for legacy elements (`jmx`, `enableRemoteStreaming`, `lib`). Helper
`resolve_field(name)` applies Solr's dynamicField matching (longest pattern wins).
Effective attributes (`stored`, `indexed`, `docValues`, `multiValued`) fall back from
field to type.

### `lib/gitref.py`
- `model_at(ref, core)` via `git show <ref>:<core>/conf/<file>`; `None` if absent (new core).
- `diff(old, new)` → list of readable lines (`+ field x`, `- copyField a→tw`,
  `~ field status: indexed true→false`, `~ /select facet.field: +a -b`, …).
- `changed_cores(ref)` from `git diff --name-only <ref>` + untracked files; a change under
  `tests/` selects all cores.
- Ref resolution: `--ref`, else `origin/main`, else `main`; if none resolves, the
  comparison is skipped with a message (exit code unaffected).

### `lib/solr.py`
- `SolrContainer(image, cores, jar, decs_index)`: free host port from the OS; one
  `docker run -d` with each `<core>/conf` bind-mounted **read-only** under `/cores-src/`,
  the jar read-only, the DeCS index read-only at `/opt/solr/server/resources/decs/main`,
  and a startup command that builds `/var/solr/data/<core>/{conf,data,lib,core.properties}`
  inside the container and then `exec solr-foreground`. Nothing is written on the host;
  the working-tree files are what is tested. Always `docker rm -f` in a `finally`
  (unless `--keep`), also on Ctrl-C.
- Wait for `/solr/admin/cores?action=STATUS`; expose `init_failures`, `logs()`,
  `exec(cmd)`.
- `Core` client (urllib): `select(q, **params)`, `num_found(q, fq=None, handler='select')`,
  `get(path, **params)`, `update_json(docs, commit)`, `update_xml(xml, commit)`,
  `delete_all()`, `commit()`.

### `lib/base.py` (unittest base classes; each core module subclasses with `core = '…'`)
- **`StaticChecks`** (no Docker): well-formed XML; every field/dynamicField type defined;
  copyField source/dest resolve; uniqueKey defined, indexed, single-valued; every handler
  `df` and `facet.field` resolves to a field; no Solr 9 removals/leftovers (`Trie*Field`,
  `WordDelimiterFilterFactory`, `<defaultSearchField>`, `<solrQueryParser>`, legacy cache
  classes, `<jmx/>`, `enableRemoteStreaming`, explicit `/export`), one test method per item
  so each can be marked individually.
- **`CommitVisibility`**: only for cores with soft commit off and `openSearcher=false`.
  The runner posts an uncommitted probe document to every such core at one shared `t0`;
  the test waits until `t0 + 20 s` (so only the first core actually waits), asserts the
  probe is invisible, commits, asserts visible, deletes it. Skipped with `--fast`.
- **`GenericLive`**: no `initFailures` for the core; no ERROR / core-specific WARN in the
  log; fixture documents index (JSON, and XML where a `docs.xml` exists) and are counted
  after commit; bare query on `/select` hits a term placed in a `df` source field; two
  terms follow `q.op`; every `/select` `facet.field` is present in the response; `fl=*`
  returns no `stored="false"` field; `/admin/ping`; `/terms`; `/export` on a docValues
  string field returns every document; each explicitly defined handler answers status 0;
  `/config` reports the commit times from the file; `luceneMatchVersion` as in the file.
- Expected failures: `known_issues.py` maps `(core, test id)` → reason; the runner wraps
  those tests with `unittest.expectedFailure` and prints the reason. An *unexpected
  success* is reported as a failure, so the entry is removed once the config is fixed.

### `cores/test_<core>.py`
Each declares `Static`, `Visibility` (where applicable), `Generic`, and for the converted
cores a `Specific` class:
- **relatos-experiencia**: port of the 42 checks (same documents and expectations as the
  preserved script; the facet-tie and `/query df=text` corrections already in it).
- **best-practices**: from `bp-docs.json` + log: `tw` = title + introduction; 11 facets and
  per-field `facet.limit`; `fq` on `country`, `is_private`, combined; 48,000-character
  `outcome_information`; `status` returned but not filterable; catch-all field; string
  sort; accents/hyphens/phrase; wildcard/prefix; boolean operators; edismax `qf`; paging;
  highlighting; tagged/excluded facets; delete by id; `wt=xml|php|phps`; `/query` `df=text`
  with AND on an explicit field; `/related`.
- **fi-admin**: from `docs.json` + log/plan 003: one doc per `django_ct`; AND/`df=tw`;
  `fq` on `status`/`django_ct` incl. wildcard; all 31 facets and per-field `facet.limit`;
  sort on `title_sort` (case/accent-insensitive), `status`, `start_date`; date range;
  hyphenated terms; DeCS expansion on `descriptor`/`mh`/`mj` and precoded `tw`
  (translation, synonym, category code — exact terms re-derived with `/analysis/field`
  against the local index during implementation, starting from `^d8569`);
  `descriptor_filter` facet values are bare codes; `collection_*` and catch-all dynamic
  fields; `fl=*` hides `stored="false"` fields; a >32766-byte value in each of the five
  `indexed="false"` string fields; `/related`, `/export`.
- **portal**, **api-metrics**: `Static` + `Generic` (+ `Visibility` for api-metrics) with
  a small hand-written fixture; no `Specific` class yet.
- DeCS cores raise `SkipTest` for all live classes when the jar or index is missing, with
  the path that was looked for.

### `tests/run.py`
```
python3 tests/run.py [CORE ...] [--changed] [--ref REF] [--strict] [--image IMAGE]
                     [--static-only] [--fast] [--keep] [-v]
```
Flow: resolve cores → print "Changes vs <ref>" per core → run static classes → unless
`--static-only`: check Docker, start one container with the selected (available) cores,
post probes, run per core `Visibility` → `Generic` → `Specific`, remove the container →
summary table per core (passed / failed / skipped / expected failures) → exit 0, 1
(failures, or differences with `--strict`) or 2 (usage / Docker unavailable).
A core that fails to load makes its `Generic` load test fail and the rest of its live
tests skip, without affecting the other cores.

## Steps

1. **Branch, rescue, README fix.** `git checkout -b feature/config-test-suite`; copy the two
   surviving fixture files into `tests/fixtures/{fi-admin,best-practices}/docs.json`;
   commit `best-practices/README.md` alone ("Correct /query note in best-practices README").
2. **Static layer.** `lib/config.py`, `lib/gitref.py`, `lib/base.py:StaticChecks`,
   `run.py` with `--static-only`, `--ref`, `--changed`, `--strict`; core modules with only
   `Static`. Run on all five cores; verify the diff output by temporarily editing a field
   in the working tree (and reverting).
3. **Container + discovery.** `lib/solr.py`; start all five cores on `solr:9.9` and record
   what actually happens with `portal` and `api-metrics` (load, warnings, `/export`).
   Enter the findings in `known_issues.py` with reasons. If a core cannot load at all,
   its load test is the expected failure and the remaining live tests for it skip.
4. **Generic live layer.** `GenericLive`, `CommitVisibility`, fixtures for `portal`,
   `api-metrics` and `relatos-experiencia`; green on all five.
5. **Core-specific suites**, one commit each: relatos-experiencia (port, confirm 42
   checks map 1:1), best-practices, fi-admin.
6. **README.md** (root): what each core directory is, prerequisites, the commands
   (`run.py`, `--changed`, `--static-only`, `--image solr:10`, env vars), how to read
   skips / expected failures / the diff section, how to add a check or a known issue.
   Add a one-line pointer in the three core READMEs' Validation sections.
7. **Record.** Save this plan to `.ai/plans/006-config-test-suite.md`, link it in
   `current-feature.md`, append the outcome to History. Remove
   `.ai/features/004-assets/` once the port is verified (the checks then live in `tests/`).
   No push or merge; that is `/feature complete`.

## Verification

- `python3 tests/run.py` → exit 0, all five cores reported, no leftover container
  (`docker ps -a`), no files created on the host outside `tests/`.
- `python3 tests/run.py --static-only` works with Docker stopped/unavailable.
- **Mutation checks, each reverted afterwards**, to prove the suite catches regressions:
  remove a copyField in relatos-experiencia (bare-query test fails; diff section shows
  it); change `q.op` to OR in best-practices (AND test fails); break a field type
  reference (static failure); re-add `docValues` on a stored-only string in fi-admin
  (32766-byte test fails); delete a `known_issues` entry (the run turns red).
- `IAHX_JAR=/nonexistent python3 tests/run.py` → fi-admin and portal live tests skipped
  with a message, exit 0.
- `python3 tests/run.py --changed` with a clean tree → nothing to run, exit 0; after
  touching one core → only that core.
- `python3 tests/run.py best-practices --image solr:10` runs (result reported, not
  required to pass).

## Not covered

- Fixing `portal` / `api-metrics` (only recorded as known issues).
- Core-specific suites for `portal` and `api-metrics`; client request replay; CI or hooks.
