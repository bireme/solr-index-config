# Plan: Copy documents from the Solr 5.5 cores to the Solr 9.9 cores over HTTP

## Context

`fi-admin`, `best-practices` and `relatos-experiencia` were converted from Solr 5.5 to 9.9.
Solr 9 cannot open a Solr 5 index, so the new cores start empty. The idea is a script that
reads every document from the online 5.5 core (`/select`) and posts it to the 9.9 core
(`/update`). Only `stored="true"` fields come back from a query, so anything the
application sent to a `stored="false"` field is at risk.

## Verdict

| Core | Viable? | Data loss |
|---|---|---|
| `best-practices` | Yes, straight copy | None |
| `relatos-experiencia` | Yes, straight copy | None |
| `fi-admin` | Yes, with field-specific handling | `text` for 3 document types cannot be copied exactly; `collection_*` and `media_type_filter` need recovery; 3 fields to confirm on the live index |

Fields, dynamic fields and copyFields are identical between the 5.5 and 9.9 schemas
(checked against the first commit of each core), so no field mapping is needed.

### best-practices and relatos-experiencia

The only `stored="false"` field in each is `tw`, filled only by copyField from stored
fields (`title`, `introduction` / `title`, `notes`, `description`, `fulltext`, `issue`).
Solr rebuilds it on the 9.9 side. The `indexed="false"` fields are all stored. No stored
field is a copyField destination. Copy = all stored fields minus `_version_`.

### fi-admin: `stored="false"` fields

Checked against the indexing code in `../fi-admin/src/*/search_indexes.py` and
`../fi-admin/src/templates/search/indexes/`.

| Field | How it is filled | Result |
|---|---|---|
| `tw`, `ti`, `au`, `kw`, `title_sort`, `short_title`, `descriptor_filter`, `media_collection_filter` | copyField only, from stored fields | Rebuilt by Solr. No loss |
| `text` (Haystack document field, feeds `tw`; `/query` has `df=text`) | Sent by FI-Admin from a template | Depends on document type, see below |
| `collection_*` | Sent by FI-Admin (`prepare()` in `main` and `biblioref`) | **Lost in a plain copy.** Recoverable exactly from indexed terms (unanalyzed string) |
| `media_type_filter` | Sent by FI-Admin; same expression as `media_type_display`, which is stored | **Lost in a plain copy.** Rebuild from `media_type_display` |
| `year_filter`, `ths_exact_term`, `ths_termall` | Not written by the current FI-Admin code (no thesaurus index in the checkout) | Probably empty; confirm with Luke on the live core. If populated: `year_filter` and `ths_exact_term` are recoverable from terms, `ths_termall` is not (tokenized text) |

`text` by document type:

- `biblioref` (both indexes): template is empty. No loss.
- `events`, `multimedia`, `oer`: title only. `main` resources: title + abstract. These are
  stored and already copied to `tw`. No loss for `tw`; `text:` queries need `text` rebuilt
  from those fields.
- `title`, `institution`, `leisref` acts: the template adds content that does not reach
  `tw` any other way (ISSN, subtitle; address, contacts, units; act number, year, issuer,
  ementas, notes). **This is the real loss.** It can only be approximated from stored
  fields. Recommended: copy these three types too, then run FI-Admin's `update_index` for
  just those models against the 9.9 core (they are small sets).

### fi-admin: hazards when re-sending stored fields

Three stored fields are also copyField destinations, so their stored values already
contain the copied values:

- `publication_year` ← `start_date`: single-valued. Events would be **rejected** (two values).
- `mh` ← `descriptor`, `language` ← `source_language_display`: values would be duplicated.

The script must remove from each destination the values that came from its sources.
`_version_` must be dropped in all cores (a positive value makes Solr 9 demand that the
document already exists, giving HTTP 409).

## Script

`tools/copy_index.py`, standard library only, same style as `tests/`.

```
python3 tools/copy_index.py <core> --source http://old:8983/solr/<core> --target http://new:8983/solr/<core>
        [--rows 500] [--fq ...] [--dry-run] [--verify-only]
```

1. **Rules from the schema.** Load `<core>/conf/schema.xml` with `tests/lib/config.py`
   (`load`, `copy_sources`, `effective`) to find stored copyField destinations and
   non-stored fields. No per-core hardcoding for the generic part.
2. **Preflight.** `/admin/luke` on the source: list actual field names (finds the
   `collection_*` instances) and report which non-stored, non-copyField fields have terms.
   Abort with a message if `ths_termall` has terms.
3. **Read.** `/select?q=*:*&fl=*&sort=id asc&cursorMark=…&wt=json` (cursors work on 5.5).
4. **Transform.** Drop `_version_`; subtract source values from stored copyField
   destinations; for fi-admin set `media_type_filter` from `media_type_display` and rebuild
   `text` from title/abstract for the types where that is exact.
5. **Recover term-only fields** (`collection_*`, plus `year_filter` / `ths_exact_term` if
   populated). Before the copy, for each field list its values with `/terms`, then page ids
   with `fq={!term f=<field>}<value>`, building an `id → values` map merged in step 4.
6. **Write.** POST JSON batches to `/update`; on a 400, retry the batch one document at a
   time and log failing ids to a file. Explicit commit at the end (best-practices and
   relatos-experiencia have no autocommit that opens a searcher).
7. **Verify.** Compare source and target: `numFound`, counts per `django_ct`, facet counts
   for every `/select` facet field and every recovered field, and a few `tw` queries.

Changes during the copy: either pause indexing in the application, or re-run with
`--fq updated_date:[…]`; deletions made meanwhile are not propagated.

Also: a short "Copying data from Solr 5.5" section in the root `README.md`, and a note in
`fi-admin/README.md` beside "Full reindex" listing the three document types to reindex
from FI-Admin.

## Verification

- Unit-level: run the transform on `tests/fixtures/<core>/docs.json`.
- End to end, locally: start `bireme/solr:5.5.5` with the 5.5 conf from git history
  (first commit of each core) and index the fixtures plus documents with `collection_*`,
  `media_type_filter`, an event with `start_date`, and a reference with `descriptor`/`mh`;
  start `solr:9.9` with the current conf (helpers in `tests/lib/solr.py`); run the script;
  the verify step must report equal counts, and the event must not be rejected.
- `python3 tests/run.py` still passes.
- Then a `--dry-run` against the online 5.5 cores to get the preflight report (read-only).

## Open points

- Production FI-Admin is assumed to match the local checkout in `../fi-admin`.
- A full Haystack rebuild remains the only fully lossless route for `fi-admin`; the script
  trades that for speed and for not loading the database.
