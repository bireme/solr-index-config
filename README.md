# solr-index-config

Solr core configurations used by BIREME services. Each directory holds the `conf/` of one
standalone core (`schema.xml` and `solrconfig.xml`, classic schema).

| Core | Needs analyzer jar + DeCS index | Notes |
| --- | --- | --- |
| `portal` | yes | |
| `fi-admin` | yes | FI-Admin (Django/Haystack) index; [README](fi-admin/README.md) |
| `best-practices` | no | [README](best-practices/README.md) |
| `relatos-experiencia` | no | [README](relatos-experiencia/README.md) |
| `api-metrics` | no | |

## Copying data from Solr 5.5

Solr 9 cannot open a Solr 5 index. `tools/copy_index.py` reads every document of a running
Solr 5.5 core over HTTP and posts it to the Solr 9.9 core, for `fi-admin`,
`best-practices` and `relatos-experiencia`. Standard library only.

```
python3 tools/copy_index.py <core> --source http://old:8983/solr/<core> --target http://new:8983/solr/<core> --dry-run
python3 tools/copy_index.py <core> --source ... --target ...
python3 tools/copy_index.py <core> --source ... --target ... --verify-only
```

`--dry-run` only reads the source: it reports what will happen to each unstored field and
prints the first document as it would be sent. A real run copies, commits, and compares
document and facet counts between the two cores (`--query 'tw:dengue'` adds result-count
comparisons). Exit code: `0` equal, `1` rejected documents or differences, `2` error.
Other options: `--rows`, `--fq` (copy a subset), `--failed-file`.

A query only returns stored fields, so the script reads the core's `schema.xml` here and:

- drops `_version_`;
- leaves fields filled only by copyField (`tw`, `ti`, `title_sort`, …) for Solr to rebuild;
- removes the copied values from stored copyField destinations (in `fi-admin`: `mh`,
  `language`, `publication_year`), which would otherwise be duplicated or rejected;
- reads unstored string fields back from their indexed terms (in `fi-admin`:
  `collection_*`, `media_type_filter`, and `year_filter` / `ths_exact_term` if present).

`best-practices` and `relatos-experiencia` are copied without loss. `fi-admin` is not:
see ["Copying from the Solr 5.5 core"](fi-admin/README.md#copying-from-the-solr-55-core).

Stop indexing in the application during the copy, or run it again afterwards with `--fq`
on the changed documents. Deletions made during the copy are not carried over.

## Testing

Run the tests whenever a `schema.xml` or `solrconfig.xml` changes, before pushing.

```
python3 tests/run.py                  # everything: static checks + live checks on Solr
python3 tests/run.py --changed        # only the cores whose conf/ differs from origin/main
python3 tests/run.py fi-admin portal  # only these cores
python3 tests/run.py --static-only    # only the checks that need no Docker (instant)
```

Requirements: Python 3.9+ (standard library only) and Docker for the live checks. The
first run pulls the `solr:9.9` image. A full run takes about a minute.

### What is checked

1. **Changes vs the git ref.** Fields, field types, copyFields, handler defaults and
   commit settings that were added (`+`), removed (`-`) or changed (`~`) compared with
   `origin/main` (`--ref` to choose another). This section is informative: read it to
   confirm the change is the one you meant. With `--strict` any difference fails the run.
2. **Static checks** (`Static`): well-formed XML; every field type, copyField, `df` and
   `facet.field` refers to something that exists; nothing removed or ignored in Solr 9 is
   used.
3. **Live checks** on a throwaway Solr container with all selected cores:
   - `Load`: the core loads, and Solr logs no error or warning for it.
   - `Visibility`: for cores with soft commit off, a document is invisible 20 s after an
     update and visible after an explicit commit (`--fast` skips this wait).
   - `Generic`: derived from the configuration itself — JSON and XML updates, default
     field and operator, every `/select` facet, `fl=*` hiding unstored fields, `/export`,
     `/terms`, ping, every search handler, commit settings.
   - `Specific`: behaviour each core must keep, written by hand in
     `tests/cores/test_<core>.py` (fi-admin, best-practices, relatos-experiencia).

The container mounts each `conf/` read-only, so the files in the working tree are what is
tested and nothing is written to the checkout. It is removed at the end; `--keep` leaves
it running and prints its URL, for debugging.

### Options and environment

| | |
| --- | --- |
| `--image IMAGE` / `SOLR_IMAGE` | Solr image to test on (default `solr:9.9`), e.g. `--image solr:10` |
| `IAHX_JAR` | `iahx-analyzer` jar for `portal` and `fi-admin` (default `../iahx/iahx-analyzer/jar/iahx-analyzer-20260119.jar`) |
| `DECS_INDEX` | DeCS Lucene index directory (default `../iahx/iahx-analyzer/resources/decs/main`) |
| `-v` | list every test |

If the jar or the DeCS index is not found, the live checks of `portal` and `fi-admin` are
skipped and the summary says so. Exit code: `0` passed, `1` failures, `2` environment or
usage error (for example Docker not running).

### Reading the summary

- **skipped**: not applicable to that core, or a dependency is missing; the reason is listed.
- **known issues**: problems that exist today and are recorded in
  `tests/lib/known_issues.py` with their reason (currently in `portal` and `api-metrics`,
  which still carry Solr 5 leftovers). They do not fail the run.
- **fixed known issues**: a recorded problem no longer occurs. The run fails until its
  entry is removed from `known_issues.py`, so the list stays accurate.

### Adding checks

- A behaviour of one core: add a `test_...` method to the `Specific` class in
  `tests/cores/test_<core>.py` (create the class from `base.LiveTest` if the core has
  none). Documents go in `tests/fixtures/<core>/docs.json`; the string `"@BIG@"` there
  stands for a 40,000-character value.
- A rule for every core: add a method to `StaticChecks` or `GenericLive` in
  `tests/lib/base.py`.
- A new core: add its directory name to `CORES` in `tests/lib/config.py`, copy one of the
  `tests/cores/` modules, and add a fixture.
