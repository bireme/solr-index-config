# 2026-11-13 — Copy documents from the Solr 5.5 cores to the Solr 9.9 cores over HTTP

Plan: `.ai/plans/007-copy-index-5-to-9.md` (no spec file; the request was a viability
analysis that became an implementation)
Usage: root `README.md`, section "Copying data from Solr 5.5"; fi-admin specifics in
`fi-admin/README.md`, section "Copying from the Solr 5.5 core"

## Question

Can a script read the documents of the online Solr 5.5 cores over HTTP and post them to
the Solr 9.9 cores, and what is lost in `fi-admin`, `best-practices` and
`relatos-experiencia` because of `stored="false"` fields?

## Analysis

Fields, dynamic fields and copyFields are the same in the 5.5 and 9.9 schemas (compared
with the first commit of each core), so no field mapping is needed.

- **best-practices, relatos-experiencia: no loss.** The only unstored field is `tw`,
  filled by copyField from stored fields. No stored field is a copyField destination.
- **fi-admin**, checked against `../fi-admin/src/*/search_indexes.py` and
  `../fi-admin/src/templates/search/indexes/` (production is assumed to match that
  checkout):

| Field | How it is filled | Outcome |
| --- | --- | --- |
| `tw`, `ti`, `au`, `kw`, `title_sort`, `short_title`, `descriptor_filter`, `media_collection_filter` | copyField only | Rebuilt by Solr |
| `collection_*` | Sent by FI-Admin (`prepare()` in `main` and `biblioref`) | Recovered from indexed terms |
| `media_type_filter` | Sent by FI-Admin | Recovered from indexed terms |
| `year_filter`, `ths_exact_term` | Not written by the current FI-Admin code | Recovered from indexed terms if present |
| `ths_termall` | Not written by the current FI-Admin code | Cannot be copied (tokenized) |
| `text` | Haystack document field, from a template per document type | See below |

`text` by document type: empty for `biblioref`; title only for `events`, `multimedia`,
`oer`; title + abstract for `main` resources (all rebuilt exactly). For `title`,
`institution` and `leisref` acts the template adds content that reaches `tw` only through
`text` (ISSN, subtitle; address, contacts, units; act number, year, issuer, ementas,
notes). **That is the real loss**; those models must be reindexed from FI-Admin.

Two problems that do not come from `stored="false"`:

- Stored copyField destinations already hold the copied values. `publication_year` ←
  `start_date` is single-valued, so events would be rejected; `mh` ← `descriptor` and
  `language` ← `source_language_display` would get duplicates.
- `_version_` must not be sent (Solr 9 answers 409 for a document that does not exist).

## What was done

- `tools/copy_index.py` (new, standard library only; reuses `tests/lib/config.py` and the
  `Core` HTTP client of `tests/lib/solr.py`):
  - rules come from the core's `schema.xml`: stored copyField destinations, and unstored
    fields that are not filled by copyField alone;
  - preflight with `/admin/luke` on the source lists the unstored fields that really exist
    (this finds the `collection_*` instances) and classifies each as recovered from terms,
    rebuilt, or not copiable; stops on a not-copiable field unless `--accept-loss`;
  - term recovery: facet on the field to list its values, then page the ids of each value
    with `fq={!term f=<field>}<value>`. Applies to `StrField`, to types whose tokenizer is
    `KeywordTokenizerFactory`, and to `year_filter` (listed by hand);
  - reads with `cursorMark` sorted by the unique key, `fl=*`;
  - transform: drop `_version_`; drop a single-valued stored copy destination when one of
    its sources is present; subtract the source values once from a multi-valued one;
    rebuild `text` per `django_ct` (table `_REBUILD`); merge recovered values;
  - writes JSON batches; a rejected batch is retried one document at a time and the
    failures go to `copy-<core>-failed.jsonl`; explicit commit at the end;
  - verification: document count, facet counts for `django_ct`, every `/select` facet
    field and every recovered field, and optional `--query` result counts;
  - options: `--rows`, `--fq`, `--query`, `--dry-run`, `--verify-only`, `--accept-loss`,
    `--failed-file`. Exit codes: 0 equal, 1 rejected documents or differences, 2 error.
- Root `README.md`: new section "Copying data from Solr 5.5".
- `fi-admin/README.md`: deploy step 4 mentions the copy; new section "Copying from the
  Solr 5.5 core" with the `text` loss and the models to reindex.

## Test

Local pair of containers: stock `solr:5.5` with the 5.5 configuration from git history
as source, `solr:9.9` with the current configuration, the analyzer jar and the DeCS index
as target. Source data: `tests/fixtures/<core>/docs.json`, plus for fi-admin a `text`
value per document and three extra documents (a reference with `descriptor`, `mh`, `mj`,
`language` and two `collection_*` fields; an act with `text`; one with `ths_exact_term`
and `year_filter`).

- best-practices (3 documents) and relatos-experiencia (2): exit 0, counts and all facets equal.
- fi-admin without `--accept-loss`: stops with exit 2 (the fixture has `ths_termall`).
- fi-admin with `--accept-loss` (14 documents): all sent, none rejected; document count
  and all 37 facets equal, including `collection_e-blueinfo_ops`, `collection_tmgl`,
  `collection_x`, `media_type_filter`, `ths_exact_term`, `year_filter`. `mh`, `language`
  and `publication_year` identical on both sides for the reference and for an event with
  `start_date`.
- `--query 'text:issnonlyintext'` (a word only in a title's `text`): 1 on the source, 0 on
  the target. This is the documented loss.
- `--dry-run`, `--verify-only` and an unreachable source (exit 2 with a message) behave as
  described. `python3 tests/run.py --static-only` still passes. Containers removed.

## Limits of the test

- **Not run against the online 5.5 cores.**
- The `bireme/solr:5.5.5` image could not be pulled, so the 5.5 source had the
  `org.bireme.dia.analysis.*` analyzers replaced by `WhitespaceAnalyzer`. Because of that
  `tw:saude` returned 0 on the source and 5 on the target; this difference is from the
  stand-in, not from the copy.
- Only a few documents; speed and memory on the real index are unmeasured. Term recovery
  costs one cursor per distinct value and keeps an `id → values` map in memory.

## Deviations from the plan

- `media_type_filter` is recovered from its terms like the other string fields, not
  rebuilt from `media_type_display`.
- Sample `tw` queries in the verification are not automatic; they are given with `--query`.
- `--accept-loss` was added; with it the script continues past `ths_termall`.
- No unit test file was added for the transform; it was exercised only in the end-to-end run.

## Open

- Run `--dry-run` against the online cores to see which unstored fields exist there.
- `manage.py update_index title institution leisref` in `fi-admin/README.md` is written
  from memory of Haystack and was not run.
- Changes and deletions made in the source during a copy are not carried over.
- Nothing is committed; `.ai/current-feature.md` was not updated.
