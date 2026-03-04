# Buildbarn Infrastructure Tuning

Use GetBuildbarnConfig to read the live jsonnet configuration, then correlate with metrics
from the infrastructure tools to identify tuning opportunities.

## Storage Tuning

### Content Addressable Storage Sizing
Buildbarn's local storage backend writes blobs into a large file or raw block device divided
into **blocks** that rotate through roles: old → current → new. A cuckoo hash table indexes
blob locations.

**How to assess if storage is undersized**:
1. GetStorageHealth: `eviction_age` — how long blobs survive before being overwritten.
   If eviction age < 7 days, the cache is under pressure.
2. GetCacheTrends: `CACHE_EVICTED` miss reason rate. If significant, storage is the bottleneck.
3. GetStorageHealth: hash table health — if get/put attempt counts approach the configured
   maximums (typically GET=16, PUT=64), the hash table is too small.

**Sizing guidance**:

| Signal | State | Recommendation |
|--------|-------|----------------|
| Eviction age < 2 days | Critical | Double disk size or add a storage shard |
| Eviction age 2-7 days | Moderate | Increase disk by 50%; monitor trend |
| Eviction age > 14 days | Healthy | No change needed |
| Hash table attempts near max | Collisions rising | Increase key_location_map size; ensure entry count is prime |
| High FindMissing rates | Clients re-checking existence | Enable existence caching on frontend |

**Block configuration tradeoffs** (from GetBuildbarnConfig):
- `oldBlocks`: More = better least-recently-used approximation but more I/O overhead from
  copy-forward. Too few = first-in-first-out eviction. Typical: 6-8.
- `currentBlocks`: Majority of the device. More = larger stable storage. Typical: 24-46.
- `newBlocks`: Where writes land. Content Addressable Storage should use 2-4 to stagger
  expiration times. Action Cache needs only 1.
- `spareBlocks`: Buffer to allow reads to complete before block rotation. Typical: 3-4.

**Maximum blob size** = `device_size / total_blocks`. If actions produce larger outputs, they
fail. Check GetStorageHealth for storage errors with large blobs.

### Sharding
Storage is typically sharded across multiple backends (Hermetiq uses 2 in development, 3 in
production). Each shard has a `weight` for proportional traffic distribution.

**When to add shards**: Write contention visible as Put latency spikes; single shard
approaching capacity; need for rolling upgrades.

**When not to add shards**: Sharding spreads data — losing a shard loses that fraction of
storage. For durability, combine with mirrored replication.

### Completeness Checking
Wraps the Action Cache to verify that all output blobs referenced by an action result still
exist in Content Addressable Storage before returning it. Essential for builds without the
bytes where Bazel defers downloading outputs.

`maximumTotalTreeSizeBytes` limits directory tree validation size. Hermetiq production uses
256 MB versus 64 MB in development. Increase if actions produce very large output trees.

## Worker Tuning

### Concurrency
The `concurrency` setting controls parallel actions per worker. Must match available CPU
and memory.

**How to assess**:
1. GetWorkerFleetHealth: CPU utilization per worker.
   - Consistently >85% → concurrency too high, actions contend for CPU.
   - Consistently <50% → concurrency too low, worker capacity wasted.
2. GetBuildbarnEvents: out-of-memory kills → concurrency × per-action memory exceeds limit.
3. High execution time variance within the same mnemonic → resource contention.

**Starting point**: `concurrency = vCPU count - 1` (headroom for the worker process).
I/O-bound workloads can exceed vCPU count.

### Input Population Strategy
- **Native (hardlinking)**: Downloads all inputs before execution. Uses a local file cache
  with least-recently-used eviction. Population time proportional to file count.
  Best when actions read most of their inputs.
- **Virtual filesystem (FUSE or NFSv4)**: Files fetched lazily on first read. Reduces storage
  reads for over-specified actions. Drawback: sequential file fetches.
- **With prefetching** (recommended for virtual filesystem): Workers profile which files
  actions actually access, then pre-download them in parallel. With prefetching, workers
  spend <1% of time fetching inputs.

**Diagnosing input fetch issues**:
1. High `input_fetch_ms` → workers are slow to stage inputs
2. GetWorkerFleetHealth: `input_root_population` stage timing
3. Native mode: check file cache size and `maximumCacheFileCount`
4. Virtual filesystem mode: check if prefetching is enabled in GetBuildbarnConfig

### Worker File Cache
- `maximumCacheFileCount`: Increase if actions have wide input trees.
- `maximumCacheSizeBytes`: Must accommodate the most common input files.
- **Signal cache is too small**: Input fetch times improve for repeated builds of the same
  targets but degrade when switching targets.
- **Invocation stickiness** on the scheduler helps by routing the same invocation's actions
  to the same workers, keeping file caches warm.

## Scheduler Tuning

### Platform Queue Management
The scheduler maintains separate queues per platform. Actions match to queues based on
platform properties (operating system family, container image, instruction set architecture).

**Diagnosing platform issues**:
1. GetSchedulerQueueHealth shows per-platform breakdown
2. One platform with high queue depth while others are idle → that platform is under-provisioned
3. `platformQueueWithNoWorkersTimeout` (default 900 seconds) — queues with no workers are
   removed after this duration

### Invocation Stickiness
`workerInvocationStickinessLimits` keeps a worker assigned to the same Bazel invocation for a
configured duration, improving file cache locality. Tradeoff: too much stickiness causes load
imbalance. The scheduler uses tiered durations to balance locality versus fairness.

### Size Class Routing
The scheduler can learn which worker size class (for example, 4-core versus 8-core) is optimal
per action type, using an Initial Size Class Cache. Routes small compilations to small workers
(cheaper) and expensive linking to large workers (faster).

**Signal this could help**: High cost variance within the same mnemonic — actions that finish
in 2 seconds on a large worker but 30 seconds on a small one.

## Diagnosing Infrastructure-Related Build Regressions

When builds get slower and the cause is not cache-related or code-related:

1. **Timeline correlation**: GetInfraHealthSummary for a slow build. Compare to the same
   tool for a recent fast build of the same targets.
2. **Storage**: GetStorageHealth → Is eviction age dropping? Are latencies up? Error rates?
3. **Workers**: GetWorkerFleetHealth → CPU/memory spiking? Execution stage timings changing?
   GetBuildbarnEvents for out-of-memory kills during the build window.
4. **Scheduler**: GetSchedulerQueueHealth → Queue depth growing? Specific platforms backed up?
5. **Network**: GetGrpcHealth → Error rates or latencies elevated between components?
6. **Configuration**: GetBuildbarnConfig → Has anything changed? Compare concurrency, storage
   sizes, and shard counts to what metrics suggest is needed.

## Infrastructure Scaling Decision Framework

| Metric | Threshold | Action | Expected Impact |
|--------|-----------|--------|-----------------|
| Queue wait 90th percentile > 10 seconds | Sustained over 1 hour | Add workers for affected platform | Reduces queue wait proportional to workers added |
| Eviction age < 3 days | Sustained trend | Increase disk or add storage shard | Reduces `CACHE_EVICTED` misses |
| Worker CPU > 85% | Sustained during builds | Reduce worker concurrency or add workers | Reduces execution time variance |
| Worker memory > 80% | With out-of-memory kills | Increase worker memory limits | Eliminates out-of-memory action failures |
| Storage Get 90th percentile > 100 milliseconds | Sustained | Increase key_location_map; check disk I/O | Reduces input fetch and cache lookup times |
| Service mesh error rate > 1% | Any sustained period | Investigate specific error codes | Reduces action failures and retries |
| Fleet utilization < 30% | Sustained over 7+ days | Reduce fleet size or improve autoscaler | Reduces infrastructure cost |
