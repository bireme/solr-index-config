# relatos-experiencia — Solr 9.9 core configuration

Configuration of the `relatos-experiencia` core, converted from Solr 5.5 to Solr 9.9
(Lucene 9.12). It comes from the same Solr 5.5 template as `best-practices/conf` and
follows the same conversion; `solrconfig.xml` differs from the best-practices one only in
the `/select` facet fields. The Solr 5.5 originals are the first commit of this directory
in git history.

## Deploying

1. **Solr 9.9.** Standalone core, classic `schema.xml` (`ClassicIndexSchemaFactory`).
2. **No custom jar, no DeCS index.** The core uses only analysis components shipped with
   Solr. It does not need `iahx-analyzer` or `resources/decs/main`.
3. **Full reindex.** Solr 9 cannot open a Solr 5 index. Start with an empty `data/`
   directory and reindex from the source application.
4. **Optional system properties.** Solr 9 ignores `enableRemoteStreaming` in
   `solrconfig.xml`. If anything depends on `stream.url`, `stream.file` or `stream.body`,
   start Solr with `-Dsolr.enableRemoteStreaming=true` and/or `-Dsolr.enableStreamBody=true`.

## What changed from the Solr 5.5 configuration

### schema.xml

- Numeric and date types use Point fields (`IntPointField`, `DatePointField`, …) in place
  of the removed Trie fields. `_version_` uses `plong`.
- `string` and the Point types have docValues.
- The stored-only date strings `start_date`, `end_date`, `partial_date` and `other_date`
  (`indexed="false"`) set `docValues="false"`. They stay returned-only values as before,
  and values longer than 32766 bytes are still accepted.
- The DeCS field types (`decs`, `decs_simple`, `decs_keyword`, `decs_code`,
  `decs_qualifier`, `decs_authorized_category`, `text_with_decs`) were removed. No field
  used them, and on Solr 9 they would require the analyzer jar and a DeCS index just to
  load the core. If a DeCS field is needed later, copy the types from
  `fi-admin/conf/schema.xml`.
- `WordDelimiterFilterFactory` became `WordDelimiterGraphFilterFactory`, with the same
  parameters, in `text` and `textSpell`.
- `<defaultSearchField>` and `<solrQueryParser>` were removed from the schema; see below.
- Schema version is `1.6`. All fields, the catch-all dynamic field and the five
  copyFields (`title`, `notes`, `description`, `fulltext`, `issue` → `tw`) are unchanged.

### solrconfig.xml

- `luceneMatchVersion` is `9.12`.
- Default operator AND is now `q.op=AND` in the `/select` and `/query` defaults; the
  default field stays `df=tw` on `/select`.
- Cache `class` attributes were removed (Caffeine is the only implementation); sizes are unchanged.
- `numVersionBuckets`, `<jmx/>` and `enableRemoteStreaming` were removed: Solr 9 ignores
  or no longer supports them.
- The explicit `/export` handler was removed. Solr 9 provides `/export` implicitly; the
  Solr 5 definition still loads but turns it into a plain search limited to `rows`.
- Commit policy and the `/select` facet fields (`population_group`, `thematic_area`,
  `country`, `collection`) are unchanged.

## Behaviour to be aware of

- **Documents appear only after an explicit commit.** The hard commit runs every 15
  seconds without opening a searcher and soft commits are disabled, exactly as in the
  Solr 5.5 configuration. The indexing client must send `commit=true` (or a commit
  request) for changes to become searchable.
- The default field `tw` contains only `title`, `notes`, `description`, `fulltext` and
  `issue`. Other fields are searched with an explicit field name (`keywords:…`,
  `objectives:…`).
- `/query` has `df=text`, as in 5.5 (the handler default overrode the schema's
  `defaultSearchField`), so a bare query there searches the catch-all field `text`, not
  `tw`. Use `/select` or an explicit field.
- The date fields are strings and stored-only: they cannot be searched, filtered or
  sorted, as in 5.5.
- `title` is a tokenized `text` field, so `sort=title asc` does not sort alphabetically.
- `/export` only accepts fields with docValues (the indexed `string` fields).

## Validation

Tested on 2026-11-10 with the stock `solr:9.9` Docker image (Solr 9.9.0), with no extra
jar: the core loads with no errors and no configuration warnings; documents index through
JSON and XML updates, including 40,000-character values in `other_date` and
`lessons_learned`; a document is not visible before an explicit commit and is after it;
bare queries find terms from each of the five `tw` sources and not from other fields;
AND semantics on `/select` and `/query`; accented, hyphenated and phrase queries; all 4
`/select` facets; `fq` on `status`, `country`, `thematic_area` and combined; `fl=*`; the
catch-all dynamic field; sorting on a string field; `/related`, `/terms`, `/export` and
`/admin/ping` respond as expected; commit settings 15 s / `openSearcher=false` / soft
commit off. Not tested: the real requests of the application that uses this core, which
was not available.
