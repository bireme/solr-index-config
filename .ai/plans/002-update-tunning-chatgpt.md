# Solr 9.10.1 Indexing and Optimize Tuning Recommendations

## 1. Environment

This document summarizes the recommended Solr configuration for a server dedicated exclusively to **bulk indexing and index optimization**, with no search traffic during the build process.

### Current environment

- **Solr:** 9.10.1
- **Java:** Eclipse Adoptium OpenJDK 17.0.19
- **CPU:** 16 processors
- **Physical RAM:** 64 GB
- **Java heap:** 8 GB (`-Xms8g -Xmx8g`)
- **Index size:** approximately 472 GB
- **Documents:** approximately 42,868,067
- **Workload:** full index build followed by optimize
- **Search traffic:** none on this server
- **`maxSegments=1`:** not used

The storage type was not provided. The merge-thread recommendations below assume reasonably fast local SSD/NVMe storage. If the index resides on SATA SSD, SAN, NFS, network storage, or HDD, merge concurrency should be benchmarked more conservatively.

---

## 2. Main tuning strategy

Because this machine is not serving queries, the configuration should favor **maximum indexing and merge throughput** rather than query latency.

The most important principles are:

1. Keep most physical RAM available to the operating system filesystem cache.
2. Use a larger IndexWriter RAM buffer to create larger initial segments.
3. Disable Lucene merge I/O throttling during the dedicated build/optimize workload.
4. Permit more concurrent merges than a normal search node.
5. Avoid soft commits and avoid opening searchers unnecessarily.
6. Use `overwrite=false` only when every document ID is guaranteed to appear once during the build.
7. Do not force the final index into one segment.
8. Measure **total build time = indexing time + optimize time**, not just one phase.

---

## 3. Recommended JVM memory strategy

The current Java heap is:

```text
-Xms8g -Xmx8g
```

With 64 GB of physical RAM, this is a good starting point.

A large Lucene index benefits substantially from the operating system page cache. Giving excessive memory to the JVM can reduce filesystem cache and hurt indexing/merge throughput.

Recommended starting layout:

```text
Physical RAM:       64 GB
Java heap:           8 GB
OS/filesystem:     ~56 GB
```

Do **not** increase the heap simply because more RAM is available.

Consider moving to 12-16 GB heap only if GC logs or heap metrics show real memory pressure during indexing.

---

## 4. Recommended `<indexConfig>`

Recommended starting configuration:

```xml
<indexConfig>

  <lockType>native</lockType>

  <!--
    Increase the IndexWriter RAM buffer.
    Solr's normal value is much smaller and is conservative for general workloads.
    A 1 GB buffer is appropriate to test with an 8 GB heap and one active build.
  -->
  <ramBufferSizeMB>1024</ramBufferSizeMB>

  <!--
    Avoid compound-file overhead during bulk indexing and merging.
  -->
  <useCompoundFile>false</useCompoundFile>

  <!--
    TieredMergePolicy remains a good choice.
    Allow somewhat more segments during the indexing phase so normal background
    merging is less aggressive. The final optimize step performs consolidation.
  -->
  <mergePolicyFactory class="org.apache.solr.index.TieredMergePolicyFactory">
    <int name="maxMergeAtOnce">10</int>
    <int name="segmentsPerTier">20</int>
    <int name="targetSearchConcurrency">1</int>
    <double name="maxMergedSegmentMB">5000</double>
  </mergePolicyFactory>

  <!--
    More aggressive merge scheduler for a dedicated build node.
    Start with 6 merge threads and benchmark against 4 and 8.
  -->
  <mergeScheduler class="org.apache.lucene.index.ConcurrentMergeScheduler">
    <int name="maxMergeCount">11</int>
    <int name="maxThreadCount">6</int>
    <bool name="ioThrottle">false</bool>
  </mergeScheduler>

  <!--
    InfoStream is useful for Lucene debugging but can create heavy logging overhead.
  -->
  <infoStream>false</infoStream>

</indexConfig>
```

---

## 5. Why these settings are recommended

### `ramBufferSizeMB=1024`

The RAM buffer controls how much indexing data Lucene buffers before flushing a new segment.

A larger buffer generally means:

```text
larger RAM buffer
      ↓
fewer flushes
      ↓
fewer/smaller initial segments
      ↓
less merge work later
```

For this server, benchmark these values if needed:

```text
512 MB
1024 MB   <- recommended starting value
1536 MB
```

Do not immediately jump to 2-4 GB with an 8 GB Java heap because IndexWriter memory usage can temporarily exceed the configured buffer.

---

### `useCompoundFile=false`

Compound files reduce the number of files per segment, but they add extra work during creation and are generally not useful when the priority is maximum batch-indexing throughput.

For a dedicated indexing server, leaving compound files disabled is appropriate.

---

### `segmentsPerTier=20`

The default policy is more conservative for mixed indexing/search workloads.

Increasing `segmentsPerTier` allows more segments to accumulate before normal merging is triggered.

Conceptually:

```text
segmentsPerTier=10
index -> merge -> index -> merge -> index -> merge

segmentsPerTier=20
index -------- index -------- index
                         |
                    final optimize
```

This may reduce write amplification during ingestion, but the final optimize has more work to do.

Therefore benchmark **total wall-clock time**, not just indexing speed.

Recommended comparison:

```text
segmentsPerTier=10
segmentsPerTier=20   <- recommended first alternative
```

---

### `maxMergeAtOnce=10`

Keep this at 10 initially.

This controls how many segments participate in an individual normal merge. It is not the same as the number of concurrent merge threads.

For optimize throughput, `maxThreadCount` is usually the more important concurrency setting.

---

### `maxMergedSegmentMB=5000`

Keep the approximate 5 GB merged-segment target initially.

For a 472 GB index, this means the optimized index will naturally contain roughly on the order of:

```text
472 GB / 5 GB ~= 94-95 large segments
```

This is preferable to forcing the entire index into one giant segment.

Larger values such as 10 GB can be benchmarked later, but they create larger individual merge jobs and are not automatically faster.

---

### `maxThreadCount=6`

Start with:

```xml
<int name="maxMergeCount">11</int>
<int name="maxThreadCount">6</int>
```

The server has 16 processors, but 16 merge threads would usually be excessive.

Concurrent merges are limited not only by CPU but also by:

- disk read bandwidth
- disk write bandwidth
- storage queue depth
- memory bandwidth
- filesystem behavior

Recommended benchmark sequence:

```text
4 threads / 9 max merges
6 threads / 11 max merges   <- recommended starting point
8 threads / 13 max merges
```

If storage is already saturated at 6 threads, 8 threads may be slower.

---

### `ioThrottle=false`

This is one of the most important settings for this dedicated server.

Merge I/O throttling exists to prevent merges from consuming all disk bandwidth and harming concurrent query/indexing traffic.

This server has no search workload to protect during optimize, so disabling throttling allows Lucene to use more of the available storage throughput.

Recommended:

```xml
<bool name="ioThrottle">false</bool>
```

---

### `infoStream=false`

The existing configuration had:

```xml
<infoStream>true</infoStream>
```

Change it to:

```xml
<infoStream>false</infoStream>
```

InfoStream is intended for detailed Lucene debugging and can generate significant logging activity. It should normally be disabled during performance-sensitive indexing.

---

## 6. Recommended update request defaults/invariants

Current proposed configuration:

```xml
<initParams path="/update/**,/query,/select,/tvrh,/elevate,/spell">
  <lst name="defaults">
    <str name="df">text</str>
  </lst>
</initParams>

<initParams path="/update,/update/**">
  <lst name="invariants">
    <bool name="waitSearcher">false</bool>
    <bool name="overwrite">false</bool>
  </lst>
</initParams>
```

This is appropriate for a dedicated fresh-build server **if duplicate IDs are impossible**.

---

## 7. `waitSearcher=false`

Recommended invariant:

```xml
<bool name="waitSearcher">false</bool>
```

This avoids waiting for a newly opened searcher after explicit commit/optimize requests.

Since this machine does not serve searches during the build, there is no reason to wait for the searcher.

The final optimize request can therefore simply be:

```text
/update?optimize=true
```

because the invariant supplies:

```text
waitSearcher=false
```

---

## 8. `overwrite=false`

Recommended only when the build process guarantees that every unique key appears exactly once.

For example:

```text
create fresh index
      ↓
load each source record once
      ↓
42,868,067 unique documents
      ↓
optimize
      ↓
publish index
```

In this situation:

```xml
<bool name="overwrite">false</bool>
```

can improve indexing throughput because Solr does not need to perform normal replacement/duplicate-ID handling for each add.

### Important warning

If the same unique ID can occur more than once during the load, do not use `overwrite=false` as an invariant.

If future workflows may perform partial reindexing or corrective updates, prefer a default instead of an invariant:

```xml
<initParams path="/update,/update/**">
  <lst name="defaults">
    <bool name="overwrite">false</bool>
    <bool name="waitSearcher">false</bool>
  </lst>
</initParams>
```

Then a specific request can still override `overwrite=true` when replacement semantics are required.

---

## 9. Disable unnecessary searcher creation and soft commits

For a dedicated bulk index builder, soft commits are unnecessary because no user needs near-real-time visibility.

Recommended update handler concept:

```xml
<updateHandler class="solr.DirectUpdateHandler2">

  <autoCommit>
    <maxTime>1800000</maxTime>
    <openSearcher>false</openSearcher>
  </autoCommit>

  <autoSoftCommit>
    <maxTime>-1</maxTime>
  </autoSoftCommit>

</updateHandler>
```

The 30-minute hard-commit interval is only an example. The important setting is:

```xml
<openSearcher>false</openSearcher>
```

This persists the index without opening a new searcher.

If the build can be restarted from scratch after a failure, commits can be made less frequent.

---

## 10. Recommended optimize request

Use:

```text
/update?optimize=true
```

with the `waitSearcher=false` invariant configured in `solrconfig.xml`.

Do **not** add:

```text
maxSegments=1
```

The current workflow correctly omits it.

For a 472 GB index, allowing TieredMergePolicy to preserve its normal merged-segment size target is much better for merge parallelism than forcing the entire index toward one giant segment.

---

## 11. Final recommended combined configuration

### `indexConfig`

```xml
<indexConfig>

  <lockType>native</lockType>

  <ramBufferSizeMB>1024</ramBufferSizeMB>
  <useCompoundFile>false</useCompoundFile>

  <mergePolicyFactory class="org.apache.solr.index.TieredMergePolicyFactory">
    <int name="maxMergeAtOnce">10</int>
    <int name="segmentsPerTier">20</int>
    <int name="targetSearchConcurrency">1</int>
    <double name="maxMergedSegmentMB">5000</double>
  </mergePolicyFactory>

  <mergeScheduler class="org.apache.lucene.index.ConcurrentMergeScheduler">
    <int name="maxMergeCount">11</int>
    <int name="maxThreadCount">6</int>
    <bool name="ioThrottle">false</bool>
  </mergeScheduler>

  <infoStream>false</infoStream>

</indexConfig>
```

### Update request invariants

```xml
<initParams path="/update/**,/query,/select,/tvrh,/elevate,/spell">
  <lst name="defaults">
    <str name="df">text</str>
  </lst>
</initParams>

<initParams path="/update,/update/**">
  <lst name="invariants">
    <bool name="waitSearcher">false</bool>
    <bool name="overwrite">false</bool>
  </lst>
</initParams>
```

### Update handler

```xml
<updateHandler class="solr.DirectUpdateHandler2">

  <autoCommit>
    <maxTime>1800000</maxTime>
    <openSearcher>false</openSearcher>
  </autoCommit>

  <autoSoftCommit>
    <maxTime>-1</maxTime>
  </autoSoftCommit>

</updateHandler>
```

---

## 12. Recommended benchmark plan

Do not change every parameter at once if you want to know which change produced the improvement.

Recommended test sequence:

| Test | RAM Buffer | Merge Threads | I/O Throttle | Segments/Tier |
|---|---:|---:|---|---:|
| A - baseline | current | default | default | 10 |
| B | 1024 MB | default | default | 10 |
| C | 1024 MB | 6 | off | 10 |
| D | 1024 MB | 6 | off | 20 |
| E | 1024 MB | 8 | off | 20 |

For every run, record:

```text
indexing time
+
optimize time
=
total build time
```

The best configuration is the one with the lowest **total build time**, not necessarily the fastest indexing phase or fastest optimize phase individually.

---

## 13. Storage monitoring during optimize

The storage device is likely to be the main bottleneck during a 472 GB forced merge.

Run during optimize:

```bash
iostat -x 1
```

Watch especially:

- read MB/s
- write MB/s
- `%util`
- `await`
- queue depth

Also monitor CPU:

```bash
pidstat -dru -p $(pgrep -f start.jar) 1
```

Interpretation:

### Storage saturated, CPU not saturated

The job is I/O-bound.

Increasing merge threads further will probably not help.

### CPU heavily utilized, storage has headroom

Testing 8 merge threads may help.

### Both CPU and storage have significant headroom

Investigate merge throttling, thread limits, filesystem/storage configuration, or whether only a small number of very large merges remain.

---

## 14. Priority order

For this exact workload, the recommended optimization priority is:

1. `infoStream=false`
2. `ioThrottle=false`
3. `ramBufferSizeMB=1024`
4. `waitSearcher=false`
5. `openSearcher=false`
6. disable soft commits
7. `overwrite=false` if IDs are guaranteed unique
8. start with 6 merge threads
9. benchmark `segmentsPerTier=20`
10. only then test 8 merge threads or larger merged-segment sizes
11. tune JVM heap only if GC metrics demonstrate a problem

---

## 15. Recommended starting point

For the current hardware and workload, the recommended first production benchmark is:

```text
Heap:                    8 GB
RAM buffer:              1 GB
Merge threads:           6
Max merge count:         11
Merge I/O throttle:      disabled
Segments per tier:       20
Max merged segment:      5 GB
Compound files:          disabled
InfoStream:              disabled
Soft commits:            disabled
Hard commit searcher:    disabled
waitSearcher:            false
overwrite:               false, only if IDs are unique
maxSegments:             omitted
```

The most important remaining factor is the storage subsystem. The final choice between 4, 6, and 8 merge threads should be made from actual `iostat` measurements during optimize.
