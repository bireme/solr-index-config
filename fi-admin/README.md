# fi-admin — Solr 9.9 core configuration

Configuration of the `fi-admin` core (FI-Admin's Django/Haystack index), converted from
Solr 5.5 to Solr 9.9 (Lucene 9.12). `portal/conf` was the reference for Solr 9 syntax and
for the DeCS analysis chains. The Solr 5.5 originals are the first commit of this
directory in git history.

## Deploying

1. **Solr 9.9.** Standalone core, classic `schema.xml` (`ClassicIndexSchemaFactory`).
2. **Analyzer jar.** Put the Lucene 9 build of `iahx-analyzer` in `<instanceDir>/lib/`
   (for example `/var/solr/data/fi-admin/lib/iahx-analyzer.jar`). Solr loads that directory
   automatically; no `<lib>` directive is used. The Solr 5 jar does not load.
3. **DeCS index.** `org.bireme.dia.filters.SynonymFilterFactory` opens the DeCS Lucene
   index at `resources/decs/main`, relative to Solr's working directory, which is the
   `server` directory of the installation. In the official Docker image that is
   `/opt/solr/server/resources/decs/main`. The index must be in Lucene 9 format.
4. **Full reindex.** Solr 9 cannot open a Solr 5 index. Start with an empty `data/`
   directory and rebuild the index from FI-Admin, or copy the documents from the running
   Solr 5.5 core (see "Copying from the Solr 5.5 core" below).
5. **Optional system properties.** Solr 9 ignores `enableRemoteStreaming` in
   `solrconfig.xml`. If anything depends on `stream.url`, `stream.file` or `stream.body`,
   start Solr with `-Dsolr.enableRemoteStreaming=true` and/or `-Dsolr.enableStreamBody=true`.

## What changed from the Solr 5.5 configuration

### schema.xml

- Numeric and date types use Point fields (`IntPointField`, `DatePointField`, …) in place
  of the removed Trie fields. `_version_` uses `plong`.
- `string` and the Point types have docValues, which Solr 9 needs to facet and sort on
  Point fields (`status` is a facet).
- `string_no_stored` is used by the `stored="false"` string fields (`media_type_filter`,
  `media_collection_filter`, `short_title`, `collection_*`) so they are not returned by `fl=*`.
- String fields with `indexed="false"` (`link`, `english_title`, `reference_source`,
  `time_period_textual`, `contact_email`) set `docValues="false"`: they are only returned,
  and docValues would reject values over 32766 bytes.
- The DeCS types (`decs`, `decs_simple`, `decs_keyword`, `decs_qualifier`,
  `decs_authorized_category`, `text_with_decs`) are portal's tokenizer +
  `SynonymFilterFactory` chains instead of the `org.bireme.dia.analysis.*Analyzer` classes.
- `WordDelimiterFilterFactory` became `WordDelimiterGraphFilterFactory`, with the same
  parameters as before in `text` and `textSpell`.
- `<defaultSearchField>` and `<solrQueryParser>` were removed from the schema; see below.
- Schema version is `1.6`. Fields, dynamic fields and copyFields are unchanged.

### solrconfig.xml

- `luceneMatchVersion` is `9.12`.
- Default operator AND is now `q.op=AND` in the `/select` and `/query` defaults; the
  default field stays `df=tw` on `/select`.
- Cache `class` attributes were removed (Caffeine is the only implementation); sizes are unchanged.
- `numVersionBuckets`, `<jmx/>`, `enableRemoteStreaming` were removed: Solr 9 ignores or
  no longer supports them.
- The explicit `/export` handler was removed. Solr 9 provides `/export` implicitly; the
  Solr 5 definition still loaded but turned it into a plain search limited to `rows`.
- Commit policy is unchanged: hard commit every 10 minutes without opening a searcher,
  soft commit every 60 seconds, transaction log enabled.

## Behaviour differences to be aware of

- `decs_keyword` (`descriptor`, `mh`, `mj`) is indexed without positions, as in portal.
  Each value is a single token, so quoted single-term queries work, but slop/proximity
  queries on these fields are not possible.
- `tw` expands only precoded descriptors (`^dNNNN`, `^dNNNN^sNNNN`) into their
  translations, synonyms and category codes. Free-text words are not expanded there;
  `descriptor`, `mh` and `mj` expand plain terms too.
- `/export` only accepts fields with docValues (`string`, numeric and date fields).

## Copying from the Solr 5.5 core

`python3 tools/copy_index.py fi-admin --source ... --target ...` (see the
[root README](../README.md#copying-data-from-solr-55)) copies the documents over HTTP. It
is faster than a rebuild and does not touch the database, but one field is not copied
exactly:

- `text` (Haystack's document field) is not stored. FI-Admin fills it from a template per
  document type; it feeds `tw` and is the default field of `/query`. The script rebuilds
  it where the template only uses stored fields: `main.resource` (title + abstract),
  `events.event`, `multimedia.media` and `oer.oer` (title); `biblioref` sends it empty.
  For the other types — `title.title`, `institution.institution`, `leisref.act` — the
  template adds content that reaches `tw` only through `text` (ISSN and subtitle; address,
  contacts and units; act number, year, issuer, ementas and notes). After the copy, rebuild
  those models from FI-Admin against the new core (`manage.py update_index title
  institution leisref`). The script lists the affected types and their document counts.
- `ths_termall` is tokenized and not stored, so it cannot be copied. The current FI-Admin
  code does not write it; if the source index has it, the script stops unless
  `--accept-loss` is given.

The other unstored fields are recovered: `collection_*`, `media_type_filter`,
`year_filter` and `ths_exact_term` from their indexed terms, the rest by copyField.

## Validation

Tested on 2026-11-10 with the `solr:9.9` Docker image (Solr 9.9.0),
`iahx-analyzer-20260119.jar` and a Lucene 9.12 DeCS index: the core loads with no errors
and no configuration warnings; sample documents of every `django_ct` family index through
JSON and XML updates; default-field and AND queries, `fq` on `status` / `django_ct`
(including wildcards), all `/select` facets, sorting on `title_sort`, `status` and
`start_date`, date ranges, DeCS expansion, `/related`, `/terms`, `/export` and
`/admin/ping` respond as expected. Not tested: a token-for-token comparison with the
running Solr 5.5 core, and FI-Admin itself (pysolr / django-haystack) against Solr 9.

These checks are kept as automated tests: `python3 tests/run.py fi-admin` (see the [root README](../README.md#testing)).
