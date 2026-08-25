# 2026-08-25 — solrconfig trim + schema `omitPositions` draft

Follow-up to `.ai/plans/001-update-tunning-claude.md` and `.ai/plans/002-update-tunning-chatgpt.md`.

**Trigger:** the earlier `solrconfig.xml` tuning was deployed to production but full
rebuild and optimize times improved only marginally. The question raised was whether the
new configuration was actually being loaded by the running core.

**Answer: it was loaded.** The problem is that the settings do not address the real
bottleneck. See §2.

---

## 1. Production state measured (2026-08-25)

Server `SERVER:8989:8989`, core `portal`, standalone (no SolrCloud).

| Property | Value |
| --- | --- |
| Solr / Lucene | 9.10.1 / 9.12.2 |
| `instanceDir` / `dataDir` | `/var/solr/portal` / `/var/solr/portal/data/` |
| Documents | 43,577,092 (`maxDoc` identical) |
| Index size | **480 GB** (~11 KB/doc) |
| Segments | 51 (most ~600 MB, one 4.2 GB) |
| **Deleted docs** | **0 — `hasDeletions: false`, `delCount=0` on every segment** |
| CPUs / load avg | 16 / 7.63 |
| Physical RAM | 63 GB (~2.5 GB free) |
| Heap | 8 GB (`-Xms8g -Xmx8g -XX:+UseG1GC -XX:MaxGCPauseMillis=250`) |
| Swap | 1.9 GB total, **16 KB free (fully consumed)** |
| Storage | `/dev/mapper/VG_BASES-lv_bases`, ext4, 7.0 TB, 5.0 TB used, 1.7 TB free (75%) |
| Disk type | **`ROTA=0` — non-rotational (SSD)** on all `xvd*` devices |

### Configuration load verified

`GET /solr/portal/config` returned the *effective* running config, matching the deployed
file exactly (`ramBufferSizeMB: 1024`, `useCompoundFile: false`, the custom
`mergePolicyFactory` and `mergeScheduler`, `autoCommit.maxDocs: 2000000`). Solr 9.10.1
supports every parameter used, including `targetSearchConcurrency` (Lucene 9.12+).

**Conclusion: no config-loading problem. The hypothesis is closed.**

---

## 2. Findings

### 2.1 Where the 480 GB actually is

Measured with `du` by file extension in `/var/solr/portal/data/index`:

| ext | size | contents | share |
| --- | --- | --- | --- |
| `.pos` | **243 GB** | term positions | 51% |
| `.doc` | **160 GB** | postings (doc ids + term freqs) | 33% |
| `.fdt` | 56 GB | stored fields | 12% |
| `.dvd` | 12 GB | docValues | 2.5% |
| `.tim` / `.tip` | 5.9 GB / 149 MB | term dictionary | 1% |
| `.nvd` | 545 MB | norms | — |
| `.kdd` | 257 MB | points | — |
| `.vec` / `.vex` / `.vem` | **0** | vectors / HNSW graph | 0% |

**84% of the index is postings, and half of the whole index is positional data.**

### 2.2 The `knn_vector` field is not a factor

`.vec`, `.vex` and `.vem` are all zero bytes. The `vector` field
(`schema.xml:467`, `knn_vector`, 4096 dims) is declared but never populated, so HNSW
graph construction plays no part in indexing or merge cost. This confirms the same
finding already recorded in plan 001.

### 2.3 Why optimize did not get faster

1. **`forceMerge` ignores the merge policy.** `maxMergeAtOnce`, `segmentsPerTier` and
   `maxMergedSegmentMB` govern only *background* merge selection. Optimize bypasses
   them and rewrites everything into one segment — the 5000 MB cap was never applied.
2. **It is ~1 TB of I/O** (read 480 GB + write 480 GB), a floor set by the disk.
3. **With 0 deleted docs it delivers no benefit.** Optimize exists to purge deletes and
   reduce segment count; there are no deletes to purge.

### 2.4 Why indexing improved only slightly

- `ramBufferSizeMB=1024` is working (~600 MB segments are consistent with it), but a
  larger buffer only yields fewer, larger segments — total bytes written is unchanged.
- The index (480 GB) is ~7.6× physical RAM (63 GB), so the page cache covers ~13%.
  The workload is disk-bound; Lucene-side scheduling changes cannot overcome that.
- **Three of the four `mergePolicyFactory` values were already the Lucene defaults**, so
  most of that block was a no-op. Only `segmentsPerTier` (20 vs default 10) had effect.

---

## 3. Changes applied

Both files validated as well-formed XML. Nothing committed; changes left in the working tree.

### 3.1 `portal/conf/solrconfig.xml` — deployable now, no reindex

**`mergePolicyFactory` trimmed to the single non-default value.** Removed
`maxMergeAtOnce` (10 = default), `targetSearchConcurrency` (1 = default) and
`maxMergedSegmentMB` (5000 ≈ default 5120):

```xml
<mergePolicyFactory class="org.apache.solr.index.TieredMergePolicyFactory">
    <int name="segmentsPerTier">20</int>
</mergePolicyFactory>
```

**`mergeScheduler` kept unchanged, with a comment recording why.** Deleting it was
considered and rejected: on `ROTA=0` storage Lucene's defaults are `maxThreadCount=4`,
`maxMergeCount=9` and **auto IO throttling ENABLED**, which caps merge I/O to roughly
10–20 MB/s. That throttle protects query latency on slow disks and is counterproductive
for bulk indexing on SSD, so `ioThrottle=false` is retained deliberately.

```xml
<mergeScheduler class="org.apache.lucene.index.ConcurrentMergeScheduler">
    <int name="maxMergeCount">11</int>
    <int name="maxThreadCount">6</int>
    <bool name="ioThrottle">false</bool>
</mergeScheduler>
```

Net effect: **no functional change**. This is a clarity fix so the file stops implying
tuning that was never happening. Requires a core reload to take effect.

### 3.2 `portal/conf/schema.xml` — DRAFT, requires a full reindex

Added `omitPositions="true"` to 5 `fieldType` definitions, affecting 8 fields:
**`ta`, `ta_var`, `mj`, `mh`, `pt`, `sh`, `spell`, `spell_phrase`**.

`omitPositions` was chosen over `omitTermFreqAndPositions` deliberately: it drops `.pos`
(the 243 GB target) while **preserving term frequencies**, so relevance scoring is
unaffected. `omitTermFreqAndPositions` would also shrink `.doc` but would change scores.

| fieldType | fields | justification |
| --- | --- | --- |
| `string_normalized` | `ta`, `ta_var` | Single analyzer (index+query) is `KeywordTokenizerFactory` → always exactly one token. |
| `decs_qualifier` | `sh` | `KeywordTokenizerFactory` with no token-splitting filters → single token. |
| `decs_keyword` | `mj`, `mh`, `pt` | The **query** analyzer is `KeywordTokenizerFactory`, so a multi-term phrase query can never be formed — even though `SynonymFilterFactory` emits several tokens on the index side. |
| `textSpell` | `spell` | Consumed only by the spellchecker, which works off the term dictionary. |
| `textSpellPhrase` | `spell_phrase` | `KeywordTokenizerFactory` + lowercase → single token. |

Prior to this change the schema contained **zero** occurrences of `omitPositions` or
`omitTermFreqAndPositions`; every analyzed field carried full positional data.

---

## 4. Deliberately NOT changed

- **`maxSegments=16` was NOT added to `solrconfig.xml`.** It is not an `indexConfig`
  setting — it is a parameter on the optimize *command*
  (`/update?optimize=true&maxSegments=16`, or `<optimize maxSegments="16"/>`). Placing it
  in `solrconfig.xml` would be silently ignored. With 0 deleted docs, the better action
  is to **drop the optimize step entirely**; `maxSegments=16` is the fallback if the
  pipeline requires one.

- **`decs` fieldType (`ct`, `mh_words`).** Its query analyzer is
  `WhitespaceTokenizerFactory` (schema.xml:44), so quoted phrase queries against these
  fields *are* expressible and would break. Needs confirmation of query patterns.
  `mh_words` receives 3 copyFields, so it is not a small field.

- **Field-level candidates on the shared `text` type** — `nm`, `individuo`,
  `descritor_local`, `ot`, `status_fiadmin`, `co`, `th_in`, `copyright`, `declaration`.
  Cannot be done at type level (`text` is also `ti` and `ab`, which need phrases), so
  each needs a per-field `omitPositions="true"`. Requires knowledge of query patterns.

- **`tw`** — the catch-all fed by **14 `copyField`s** and the default query field
  (`df=tw`, solrconfig.xml:463). It needs positions while it remains `df`. Everything
  copied into it is indexed twice (once in its own field, once in `tw`), so it is likely
  the largest single contributor to the 243 GB of `.pos`. Whether it should exist at all
  is an edismax/`qf` design decision, not a positions decision.

- **`overwrite=false` invariant** (solrconfig.xml, `/update` initParams). Flagged as a
  correctness risk — it disables uniqueKey dedup globally, so re-indexing an existing
  `id` appends a duplicate instead of replacing it. Safe for a from-scratch full load;
  it will silently corrupt any incremental/partial update path. Recommended to pass it
  as a request param from the full-load job rather than as a global invariant. Not
  changed pending a decision.

---

## 5. Recommended next steps

1. **Stop running optimize.** With `delCount=0` on all 51 segments it is pure I/O for no
   benefit. If some consolidation is wanted, use `maxSegments=16` on the request.
2. **Size the remaining wins on a sample before reindexing 43 M docs.** Build a throwaway
   core and index ~500 K documents three ways — as-is, with this `omitPositions` draft,
   and without `tw` — then compare `.pos`/`.doc` sizes. The ratio scales to the full index.
   The 8 fields changed here are keyword-ish and are **not** expected to be the bulk of
   the 243 GB; this draft is the risk-free floor, not the win.
3. **Evaluate removing `tw`** in favour of edismax with `qf` over the real fields. This is
   the single largest potential reduction in postings.
4. **Watch disk headroom.** `/bases` is at 75% (1.7 TB free). A full optimize of this core
   needs ~480 GB of scratch on top of the existing index — fine alone, not fine if two
   large cores optimize concurrently.
5. **Investigate swap.** 1.9 GB total and fully consumed. Swapping while mmap'ing a 480 GB
   index is pathological; check `vm.swappiness` and consider disabling swap on this host.
6. Do **not** raise the 8 GB heap. On a 63 GB box the remaining RAM is worth more as page
   cache for a 480 GB index.

---

## 6. Verification commands used

```bash
# Solr/Lucene version, JVM heap, host RAM/CPU/swap
curl -s 'http://SERVER:8989:8989/solr/admin/info/system?wt=json' | jq '.lucene, .jvm.memory, .system'

# EFFECTIVE running config (ground truth, not the file on disk)
curl -s 'http://SERVER:8989:8989/solr/portal/config?wt=json' | jq '.config.indexConfig, .config.updateHandler'

# core paths and start time
curl -s 'http://SERVER:8989:8989/solr/admin/cores?action=STATUS&core=portal&wt=json' | jq '.status.portal'

# doc counts and index sizes for all cores
curl -s 'http://SERVER:8989:8989/solr/admin/metrics?group=core&prefix=INDEX.sizeInBytes,SEARCHER.searcher.numDocs&wt=json'

# segment layout and deletion counts
curl -s 'http://SERVER:8989:8989/solr/portal/admin/segments?wt=json'

# on the Solr host: storage type and index composition
lsblk -d -o NAME,ROTA,TYPE,SIZE,MODEL
findmnt -T /var/solr/portal/data/index -o SOURCE,TARGET,FSTYPE,OPTIONS
cd /var/solr/portal/data/index && for e in vec vex vem fdt fdm tim tip doc pos nvd dvd kdd; do
  printf "%-4s %s\n" "$e" "$(du -cb *.$e 2>/dev/null | tail -1 | cut -f1 | numfmt --to=iec)"
done
```
