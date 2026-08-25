# Speeding up full rebuild + forceMerge of the `portal` Solr index

## Context

The `portal` core holds **42,868,067 documents in 472 GB on disk**, on a **standalone single-core Solr 9** server with **64 GB RAM** and **SATA SSD** storage. Two operations are too slow: the **full rebuild from scratch** and the **optimize/forceMerge** step that follows it.

The index is ~7.4× larger than physical RAM, so only a small fraction can live in the OS page cache. That makes the rebuild and the merge phases **I/O-bound on a single SATA SSD** (~500 MB/s, one device). Consequently the highest-leverage moves are, in order:

1. **Write fewer bytes** (kill the transaction log during bulk load; shrink stored fields and postings).
2. **Re-read/re-write fewer bytes** (control merge levels; do not forceMerge to one segment).
3. **Stop competing for RAM** (the current `filterCache` config can demand tens of GB of heap, starving the page cache the merges depend on).

Confirmed with the user: **full rebuild + forceMerge** are the targets; **standalone, single core** (no SolrCloud/ZooKeeper); **SATA SSD**; and the **4096-dim `vector` field is never populated** — so HNSW graph construction, which would otherwise dominate everything, is not a factor here.

Prior work on this file (uncommitted, see `git diff`) already added `ramBufferSizeMB`, an explicit merge policy/scheduler, a 30-minute `autoCommit`, and `overwrite=false`. This plan builds on that, corrects two settings in it, and adds the pieces that matter most.

---

## Critical files

- `portal/conf/solrconfig.xml` — all runtime tuning.
- `portal/conf/schema.xml` — index-size reduction (this is where the 472 GB comes from).
- **New:** `portal/conf-bulk/` — a bulk-load-only variant of the configset (see Step 2).

---

## Step 0 — Collect four facts before changing anything

These change the concrete numbers below. Run on the Solr server:

```bash
nproc                                    # CPU cores -> merge thread count
lsblk -d -o NAME,ROTA,MODEL              # confirm SSD (ROTA=0) and whether index+tlog share a device
df -h /path/to/solr/data                 # need >= 472 GB FREE for any forceMerge
ps -ef | grep -o '\-Xm[sx][0-9a-zA-Z]*'  # current heap
du -sh /path/to/solr/data/portal/data/index /path/to/solr/data/portal/data/tlog
```

Also capture the per-file-type size breakdown of the current index — it tells you whether the 472 GB is stored fields (`.fdt`), postings (`.doc`/`.pos`/`.tim`), or docValues (`.dvd`):

```bash
ls -S /path/to/solr/data/portal/data/index | head -30
for ext in fdt fdx doc pos tim tip dvd dvm nvd; do
  echo -n "$ext: "; du -ch /path/to/solr/data/portal/data/index/*.$ext 2>/dev/null | tail -1
done
```

**This breakdown decides how much of Step 4 is worth doing.** `.fdt` dominant → BEST_COMPRESSION is the big win. `.pos`/`.doc` dominant → the WordDelimiter/copyField expansion is the big win.

---

## Step 1 — Fix the `filterCache`, which can demand ~88 GB of heap

`portal/conf/solrconfig.xml:272-274`:

```xml
<filterCache size="16384" initialSize="4096" autowarmCount="0"/>
```

With 42.8M documents, a filter that matches many docs is stored as a `FixedBitSet` of `42,868,067 / 8` = **5.36 MB per entry**. 16,384 such entries is **~88 GB** — far beyond both the heap and the machine. Even if only 10% of entries become bitsets, that is ~9 GB of heap held permanently, which is 9 GB the page cache cannot use for merge I/O.

Solr 9's default `CaffeineCache` supports a RAM bound. Use it instead of an entry count:

```xml
<filterCache maxRamMB="1024" initialSize="1024" autowarmCount="0"/>
<queryResultCache maxRamMB="256" initialSize="1024" autowarmCount="0"/>
<documentCache maxRamMB="512" initialSize="1024" autowarmCount="0"/>
```

Also at `solrconfig.xml:357`: `maxWarmingSearchers` of 4 means up to four searchers each holding a full cache set concurrently. Set it to **2**.

And `queryResultCache autowarmCount="1024"` (line 290) re-executes 1024 queries on every new searcher. Keep it at **0** during the rebuild; raise to 64-128 only for the serving config once rebuild timing is fixed.

> Note: this step does not speed up indexing by itself — it stops the JVM from stealing the page cache that the merge phase needs, and it removes a latent OOM.

---

## Step 2 — Create a separate bulk-load configset (largest rebuild win)

Copy `portal/conf/` to `portal/conf-bulk/`, use it for the rebuild, then swap back to `portal/conf/` for serving. The rebuild config differs in three ways.

### 2a. Disable the transaction log

`solrconfig.xml:175-178`. Every document is currently written **twice**: once into the Lucene segment and once into the tlog. On a single SATA SSD that roughly doubles write I/O for the entire rebuild. Because this is **standalone, single core**, the updateLog buys only real-time-get, atomic updates, and crash recovery — none of which a from-scratch bulk load needs. In `conf-bulk`, comment the whole `<updateLog>` element out.

Restore it in the serving config. Verify first that nothing calls `/get` and that no client sends atomic updates (`"set"`/`"add"`/`"inc"` modifiers) — the update chain at `solrconfig.xml:817-846` uses `CloneFieldUpdateProcessorFactory` and `RegexReplaceProcessorFactory`, which work fine without a tlog.

### 2b. Fix the autoCommit for bulk load

`solrconfig.xml:201-204` currently uses `maxTime` of 30 minutes with `openSearcher=false`. Time-based commits are unpredictable under a bulk load. Use a doc count instead, so commit cadence tracks throughput rather than the clock:

```xml
<autoCommit>
  <maxDocs>2000000</maxDocs>
  <openSearcher>false</openSearcher>
</autoCommit>
<autoSoftCommit><maxTime>-1</maxTime></autoSoftCommit>
```

`openSearcher=false` and `autoSoftCommit=-1` are already correct — keep both. Issue exactly **one** explicit commit at the very end of the load.

### 2c. Trim the caches to nothing during the load

In `conf-bulk`, set every cache to `maxRamMB="32"` / `autowarmCount="0"`. No queries run during the rebuild; every MB of heap saved goes to page cache.

---

## Step 3 — Merge scheduler and merge policy

### 3a. Scheduler — 6 threads is too many for one SATA SSD

`solrconfig.xml:132-136`:

```xml
<mergeScheduler class="org.apache.lucene.index.ConcurrentMergeScheduler">
    <int name="maxMergeCount">11</int>
    <int name="maxThreadCount">6</int>
    <bool name="ioThrottle">false</bool>
</mergeScheduler>
```

Six concurrent merge threads on a single SATA SSD turn a sequential read/write pattern into a random one and will not exceed the device's ~500 MB/s. Use:

```xml
<mergeScheduler class="org.apache.lucene.index.ConcurrentMergeScheduler">
    <int name="maxThreadCount">3</int>
    <int name="maxMergeCount">8</int>
    <bool name="ioThrottle">false</bool>
</mergeScheduler>
```

`maxMergeCount` must stay `>= maxThreadCount`; the gap is the queue depth before indexing threads get stalled. `ioThrottle=false` is right for the **bulk-load** config. In the **serving** config set it back to `true` and `maxThreadCount` to `2`, so background merges cannot starve query latency.

### 3b. Merge policy — leave `maxMergedSegmentMB` low during the build

`solrconfig.xml:125-130` currently caps merged segments at 5 GB. **This is already close to right and should not be raised.** With a 1 GB RAM buffer, flushed segments are ~1 GB, so `maxMergeAtOnce=10` reaches the 5 GB ceiling in essentially a single merge level: the rebuild rewrites the index roughly *once*. Raising the cap to, say, 20 GB would add a whole extra merge level — another ~472 GB of read+write on a device that can sustain ~500 MB/s, i.e. **roughly +30 minutes of pure I/O per extra level, before any CPU cost**.

Add two parameters:

```xml
<mergePolicyFactory class="org.apache.solr.index.TieredMergePolicyFactory">
    <int name="maxMergeAtOnce">10</int>
    <int name="segmentsPerTier">20</int>
    <int name="targetSearchConcurrency">1</int>
    <double name="maxMergedSegmentMB">5000</double>
    <double name="floorSegmentMB">1024</double>
    <double name="deletesPctAllowed">50</double>
</mergePolicyFactory>
```

- `floorSegmentMB=1024` matches the flush size, so the policy stops spending passes on sub-floor segments.
- `deletesPctAllowed=50` (the maximum) prevents merges triggered purely to reclaim deletes. With `overwrite=false` a fresh rebuild has **zero deleted documents**, so this costs nothing and removes a class of pointless merges.

`ramBufferSizeMB=1024` (line 121) is a good value — Lucene caps the effective buffer near 2048 MB and larger buffers only lengthen individual flush pauses. Leave it.

---

## Step 4 — Shrink the index (compounds into every other step)

472 GB / 42.8M docs = **~11 KB per document**. Every byte removed here is a byte not written during the load, not re-read during merges, and not competing for page cache. Ranked by expected payoff, gated on the Step 0 file-size breakdown:

### 4a. `BEST_COMPRESSION` on stored fields — if `.fdt` dominates

The schema stores 84 fields, with substantial duplication of abstract text: `ab`, `super_ab`, `super_ab_en`, `super_ab_es`, `super_ab_pt`, `ab_plain`, `otherab`, `mark_ab`, plus the `ab_*` and `mark_ab_*` dynamic fields (`schema.xml:267-274, 470-471`). Solr 9 defaults to `BEST_SPEED` (LZ4). Switching costs stored-field *retrieval* speed but typically cuts `.fdt` size substantially:

```xml
<codecFactory class="solr.SchemaCodecFactory">
  <str name="compressionMode">BEST_COMPRESSION</str>
</codecFactory>
```

(`solrconfig.xml:76`.) Measure retrieval latency on a representative `fl=*` query before committing to this for the serving config — but note it applies at *write* time, so the bulk-load and serving configs must agree.

Separately, audit whether all five abstract variants genuinely need `stored="true"`. Dropping even one is ~10-15% of stored bytes.

### 4b. Token expansion — if `.pos`/`.doc`/`.tim` dominate

The `text` field type (`schema.xml:141-158`) and `text_with_decs` (`schema.xml:159-192`) both apply `WordDelimiterGraphFilterFactory` with **`catenateAll="1"` and `preserveOriginal="1"`** at index time. Together these emit the original token, each sub-part, *and* the concatenation — roughly 2-3× the postings for hyphenated and alphanumeric terms, on all 34 `text`-typed fields.

The catch-all `tw` field (`schema.xml:460`) receives copies from `ti`, `ti_*`, `ab`, `ab_*`, `otherab`, `ct`, `pt`, `mj`, `mh`, `kw`, `nm`, and `decs_syn_*` (`schema.xml:482-493, 523`) and then runs the DeCS `SynonymFilterFactory` **plus** the same WordDelimiter expansion over the union. `tw` is very likely the single largest posting list in the index and the dominant analysis-CPU cost of the rebuild.

Two candidate reductions, both requiring a query-behaviour check first:
- Drop `preserveOriginal="1"` where `catenateAll="1"` already covers the query patterns in use.
- On fields where phrase and proximity queries are never issued (candidates: `mh_words`, the `*_cluster` fields, `cn`, `pr`), set `omitTermFreqAndPositions="true"`. Positions are usually the largest single component of a text index.

Validate any analysis change with the Analysis screen / `/analysis/field` handler (already enabled at `solrconfig.xml:732`) on real queries before adopting it.

### 4c. Dead copyFields

`schema.xml:455-457` — the `spell` and `spell_phrase` field definitions are **commented out**, but `schema.xml:526-529` still copies `ti` and `au` into them. They now fall through to `<dynamicField name="*" type="ignored"/>`, so the work is done and discarded. Delete those four `copyField` lines.

### 4d. The unused `vector` field

`schema.xml:467` declares `vector` as `DenseVectorField` with `vectorDimension="4096"` and `stored="true"`. It is never populated, so it costs nothing today — but if any document ever starts sending it, `stored="true"` would write ~40 KB of stored floats per document *and* build an HNSW graph whose merges are single-threaded. Either remove the field or, if it is planned, at minimum set `stored="false"` before it is ever used.

---

## Step 5 — The forceMerge / optimize strategy

**Recommendation: do not run a full `optimize` (forceMerge to 1 segment).** The reasoning is specific to this index:

1. **There is nothing to reclaim.** `overwrite=false` (`solrconfig.xml:707-712`) means a from-scratch rebuild produces **zero deleted documents**. The usual justification for optimize — purging deleted docs — does not apply. The only benefit left is a lower segment count.
2. **`TieredMergePolicy` ignores `maxMergedSegmentMB` when `maxSegments=1`.** You would produce a **single ~472 GB segment**. That segment can never again be merged, and any future deletion in it can never be reclaimed — it would poison the index permanently.
3. **The I/O cost is the whole index, single-threaded.** Merging to one segment is one merge thread reading and writing ~472 GB with no parallelism, and it needs **472 GB of free disk** on top of the existing index at peak.

Instead:

```bash
# If a lower segment count is genuinely needed after the rebuild:
curl 'http://localhost:8983/solr/portal/update?optimize=true&maxSegments=24&waitSearcher=false'
```

With the Step 3b policy the rebuild lands at roughly 95-100 segments of ≤5 GB. Going to 24 costs one full rewrite pass; going to 1 costs the same I/O but with none of the parallelism and all of the downsides above.

**Before deciding, measure whether it is needed at all.** Benchmark your real query mix against the un-optimized index first. The difference between 100 segments and 24 is usually small, and `targetSearchConcurrency=1` (already set) is the setting that actually matters for per-query segment overhead.

---

## Step 6 — JVM heap and client-side loading

### Heap

With a 472 GB index on 64 GB of RAM, **page cache is the scarcest resource**. Once Step 1 removes the unbounded cache demand, target a heap of **~12-16 GB**, leaving ~46 GB of page cache. Use G1GC (the Solr 9 default) and confirm no `-XX:+UseParallelGC` etc. is set in `solr.in.sh`. Larger heaps here are actively counterproductive: they buy caching Solr does not need during a bulk load, at the cost of the OS caching the merges do need.

### Client-side (usually where the remaining wall-clock hides)

- **Batch**: 500-1000 documents per `/update` request. Per-document requests dominate everything else in this plan.
- **Parallelise**: run **4-8 concurrent indexing clients**. Lucene's `DocumentsWriter` shares the 1 GB RAM buffer across per-thread writers and scales well; the analysis chain (DeCS synonyms + WordDelimiter over `tw`) is CPU-bound, so a single client thread will leave the box idle. Tune upward until CPU or the SSD saturates.
- **Never** send `commit=true` or `commitWithin` per batch. `waitSearcher=false` is already an invariant (`solrconfig.xml:709`) — good.
- Use the **javabin** writer (`SolrJ` `ConcurrentUpdateSolrClient` / `Http2SolrClient`) rather than XML or JSON. XML parsing of 42.8M docs is not free.
- Send **gzipped** request bodies if the loader is on a different host.

---

## Step 7 — Two correctness/security items found along the way

Not performance, but both are in the file being changed and both are easy to fix now:

1. **`overwrite=false` is declared as an `invariant`** (`solrconfig.xml:707-712`), so it applies to *every* update forever, not just the rebuild — including incremental updates, where it silently creates **duplicate documents** instead of replacing them. Make it a system property so the bulk config can force it off while normal operation keeps the safe default:
   ```xml
   <bool name="overwrite">${solr.update.overwrite:true}</bool>
   ```
   (Or simply keep `overwrite=false` only in `conf-bulk/`, which the Step 2 split already gives you.)

2. **`enableRemoteStreaming="true"` and `enableStreamBody="true"`** (`solrconfig.xml:412-413`) let anyone who can reach the Solr port read arbitrary local files and make the server fetch arbitrary URLs (SSRF). Unless the loader depends on `stream.file`/`stream.url`, set both to `false`.

---

## Verification

Run the rebuild against a **subset** first — the full run is too long a feedback loop to tune blind.

1. **Baseline.** Rebuild 1M documents with the current `portal/conf/` on a scratch core. Record wall-clock, resulting index size, and peak RSS.
2. **Apply Steps 1-3**, rebuild the same 1M into a fresh core, and compare. Expect the tlog removal (2a) and the scheduler change (3a) to show up clearly here.
3. **Apply Step 4** selectively, driven by the Step 0 file-size breakdown, and compare index size per document.
4. **Watch during each run:**
   ```bash
   iostat -xm 5            # %util and w_MB/s on the index device -> is the SSD the ceiling?
   vmstat 5                # confirm no swapping
   # Solr admin: Overview -> segment count/size; Plugins/Stats -> UPDATE -> cumulative_adds rate
   ```
   If `%util` sits near 100%, you are I/O-bound and Step 4 (fewer bytes) is where the remaining time is. If CPU is pegged and `%util` is low, the DeCS synonym analysis on `tw` is the ceiling — add client threads and revisit 4b.
5. **Query regression.** Any Step 4 change alters analysis or storage. Capture 50-100 representative production queries, run them against the baseline and the new index, and diff result counts and top-10 ordering before promoting the config.
6. **Full run.** Only after the subset numbers are satisfactory. Confirm `df -h` shows headroom for the peak, then decide on Step 5 by benchmarking queries against the un-optimized result.

## Risks

- **Disabling the updateLog** loses crash recovery mid-load — a failure means restarting the rebuild. Acceptable for a from-scratch build; unacceptable for the serving config.
- **`BEST_COMPRESSION`** slows stored-field retrieval. Benchmark `fl=*` latency before promoting it.
- **Analysis changes (4b)** alter what matches. They require the Step 5 query regression check and a full reindex — which is exactly what is being planned, so the timing is favourable, but the check is not optional.
- **`overwrite=false`** must never reach the incremental-update path (Step 7.1).
