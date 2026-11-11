# Feature 004: Regression test suite for the Solr core configurations

## Summary

Add a test suite to this repository that is run whenever a core configuration
(`*/conf/schema.xml`, `*/conf/solrconfig.xml`) changes. It combines static checks on the
files, a comparison with a git ref, and live checks against a throwaway Solr container.

During the 5.5 → 9.9 conversions, smoke tests were written in session scratch space and
discarded. The fi-admin and best-practices checks exist only as descriptions in
`.ai/logs/`, and only the relatos-experiencia script (42 checks) survived, in a session
scratchpad. This feature turns that work into tests kept in the repository.

## Current state

- No tests, no CI (`.github/` absent), no Makefile in the repo.
- Five cores, each `<core>/conf/{schema.xml,solrconfig.xml}` with
  `ClassicIndexSchemaFactory`:

| Core | Lucene | Needs jar + DeCS | Notes |
| --- | --- | --- | --- |
| `fi-admin` | 9.12 | yes | converted 2026-11-10; checks described in `.ai/logs/2026-11-10-fi-admin-…` |
| `best-practices` | 9.12 | no | converted 2026-11-10; checks described in `.ai/logs/2026-11-10-best-practices-…` |
| `relatos-experiencia` | 9.12 | no | converted 2026-11-10; 42-check `smoke.sh` survives in a session scratchpad |
| `portal` | 9.1.1 | yes | production core (9.10.1 server); 80 facet fields; still has the explicit `/export` handler, `<jmx/>` and `enableRemoteStreaming` |
| `api-metrics` | 9.1.1 | no | also has a `managed-schema` file (unused: classic factory); still has the explicit `/export` handler |

- Local dependencies outside the repo: `../iahx/iahx-analyzer/jar/iahx-analyzer-20260119.jar`
  and `../docker-repo/solr9/resources/decs/main` (Lucene 9 DeCS index).
- The relatos-experiencia script was kept during the spec/plan steps and is now ported to `tests/cores/test_relatos_experiencia.py`; the fi-admin and best-practices sample documents were also recovered from the earlier session and are in `tests/fixtures/`.
- Tools available: Docker (`solr:9.9`, `solr:10` pulled), `python3`, `jq`, `xmllint`.

## Decisions (from the spec interview)

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Cores covered | **All five.** |
| 2 | Jar / DeCS index | Env vars `IAHX_JAR` and `DECS_INDEX`, defaulting to the local paths above. If either is missing, `fi-admin` and `portal` are **skipped with a clear message**, not failed. |
| 3 | Runner | **Python 3 standard library only** (`unittest`, `urllib`, `xml.etree`, `subprocess`): no pip installs. |
| 4 | Static reference | **Compare with a git ref** (default `origin/main`, option `--ref`): report fields, dynamicFields, copyFields, field types, uniqueKey and key handler defaults that were added, removed or changed. |
| 5 | Solr image | Default `solr:9.9`; overridable with `--image` / `SOLR_IMAGE` (e.g. `solr:10`). |
| 6 | Trigger | **Manual.** `python3 tests/run.py` runs everything; `--changed` runs only the cores whose files differ from the ref. No hooks, no CI. |
| 7 | Depth | **Rebuild + generic.** The 3 converted cores get core-specific suites rebuilt from the logs/READMEs (relatos-experiencia's 42 checks preserved). `portal` and `api-metrics` get generic, config-derived checks only, to be deepened later. |

## Goals

- `python3 tests/run.py` runs on a clean checkout with only Docker and Python 3, and exits
  non-zero if any check fails.
- Static checks run on all five cores, with no Docker needed (`--static-only`).
- The git-ref comparison reports schema and handler changes with readable output.
- Live checks for the five cores run in one throwaway Solr container that is always removed.
- `fi-admin` and `portal` run when the jar and DeCS index are found, and are skipped
  with a message when they are not.
- The core-specific checks from the three conversions are preserved as tests.
- A root `README.md` (or `tests/README.md`) explains how to run the suite and when.

## CLI

```
python3 tests/run.py [CORE ...] [--changed] [--ref REF] [--image IMAGE]
                     [--static-only] [--keep] [-v]
```

- No `CORE`: all five. `--changed`: the cores with differences against `--ref` in
  `<core>/conf/`, plus all cores if `tests/` itself changed.
- `--keep`: leave the container running for debugging and print its URL.
- Exit codes: 0 all passed (skips allowed), 1 failures, 2 usage or environment error
  (for example Docker unavailable while live tests were requested).

## Static checks (every core, no Docker)

1. Both files are well-formed XML.
2. Every `field`/`dynamicField` type is defined; every copyField source/dest resolves to a
   field or dynamicField pattern; `uniqueKey` is a defined, single-valued, indexed field.
3. No Solr 9 removals: no `Trie*Field`, `WordDelimiterFilterFactory`, `<defaultSearchField>`,
   `<solrQueryParser>`, cache `class="solr.LRUCache|FastLRUCache"`.
4. Every handler `facet.field` and `df` names an existing field (or matches a
   dynamicField).
5. **Git-ref comparison** (decision 4): a diff of the parsed model (fields with their
   attributes, dynamicFields, copyFields, type names and classes, uniqueKey, and for
   `/select` and `/query` the `df`, `q.op` and `facet.field` lists, plus autoCommit and
   autoSoftCommit times). Any difference is shown. Whether a difference fails or only
   warns is decided in the plan. Cores missing at the ref are reported as new.

Known gaps in `portal`/`api-metrics` (the explicit `/export`, `<jmx/>`,
`enableRemoteStreaming`) are tracked as **expected failures** with a pointer to the
fi-admin log finding. They are not fixed in this feature, and the run stays green
until they are.

## Live checks

Runtime: one `SOLR_IMAGE` container on a free host port. The selected cores are copied to
a temp directory: `conf/`, `core.properties`, an empty `data/`, and for DeCS cores
`lib/<jar>`. The DeCS index is mounted read-only at `/opt/solr/server/resources/decs/main`.
The container is removed afterwards (unless `--keep`). Fixtures live in
`tests/fixtures/<core>/`.

**Generic (every core, derived from the config):**
- Core loads with no `initFailures`; no ERROR and no core-specific WARN in the container log.
- A fixture document (hand-written per core, covering every declared field) indexes via
  JSON and XML and is visible after commit.
- A bare query on `/select` searches its `df`; two terms are combined with `q.op`.
- Every `/select` `facet.field` returns a facet entry.
- `fl=*` does not return `stored="false"` fields.
- `/admin/ping`, `/terms` and `/export` (on a docValues string field) answer as expected;
  `/related` where defined.
- `/config` reports the autoCommit/autoSoftCommit times from the file.

**Core-specific:**
- `relatos-experiencia`: the 42 checks from the conversion `smoke.sh`, including
  invisibility before an explicit commit, all five `tw` sources, 40,000-character values
  in `other_date`/`lessons_learned`, `fq` on `status`, and `/query` `df=text`.
- `best-practices`: from its log/review: explicit-commit visibility, `tw` =
  title + introduction, the 11 facets, `is_private` fq, 48,000-character stored-only text,
  wildcard/prefix, edismax `qf`, highlighting, tagged/excluded facets, delete by id,
  `wt=xml|php|phps`, `/query` `df=text`.
- `fi-admin`: from its log: indexing per `django_ct`, AND/`df=tw`, facets, sorts (incl.
  `title_sort`), date ranges, hyphenated terms, DeCS expansion on `text_with_decs`
  (precoded terms), the >32766-byte value in the five `indexed="false"` string fields,
  `/export`.

## Out of scope

- Fixing `portal`/`api-metrics` configs (tracked as expected failures only).
- Real client request replay, performance tests, SolrCloud.
- CI, git hooks; pinning images per production version.
- Removing `api-metrics/conf/managed-schema`.

## Open items / risks

- Fixture data for `fi-admin`/`portal` DeCS checks must use precoded terms that exist in
  the local DeCS index; the exact terms are chosen in the plan.
- The explicit-commit visibility check waits ~20 s per core with soft commit off. The
  plan should share that wait across cores or make it optional (`--fast`).
- "No core-specific WARN" depends on Solr's log format; generic Jersey/startup warnings
  must be allow-listed.
- `--changed` against `origin/main` needs a fetched remote; fall back to `main` or
  report clearly.
