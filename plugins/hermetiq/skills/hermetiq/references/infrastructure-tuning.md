# Buildbarn Infrastructure Tuning Reference

Use `analyze_buildbarn_storage` or `get_buildbarn_config` when available to read live
configuration, then correlate with metrics from the infrastructure tools to identify tuning
opportunities. If neither live config tool is present, ask the operator for the relevant
Jsonnet/ConfigMap content before making config-specific recommendations.

---

## Storage Tuning

Prefer `analyze_buildbarn_storage` when it is registered (requires Kubernetes access): it
evaluates the live storage/frontend jsonnet, validates it against the bb-storage schema,
derives block geometry and key-location-map facts, and returns rule-based findings with
severities. If it is absent, use `get_buildbarn_config` only when that tool is also present
in tools/list; otherwise ask the operator for the storage/frontend/common ConfigMap Jsonnet
or use ConfigSets tools when present, and label the result as config-supplied rather than
live-cluster verified. The underlying model lives in the MCP resource
`buildbarn://guides/storage-model`.

### Content Addressable Storage Sizing

Buildbarn's local storage backend writes blobs into a large file or raw block device divided
into **blocks** that rotate through roles: old → current → new. The block is the unit of
eviction — when the oldest new block fills, the ranges rotate and the oldest old block is
discarded whole. A fixed-size open-addressed hash table (the **key-location map**) indexes
blob locations and never grows.

**`get_storage_health` response shape** (pass `storageType: "cas"` or `"ac"` to filter):
the structured payload exposes `data.projectId`, `data.start`, `data.end`, `data.status`,
and `data.metrics[]`. Each metric row has `name`, `labels`, and `value`; the current query
reports operation telemetry. It does not expose disk health, eviction age, blob-size
percentiles, or key-location-map saturation, so obtain those measurements from the operator
or another verified source before using the sizing guidance below.

**How to assess if storage is undersized**:
1. Operator-supplied eviction age — the age of the youngest data ever evicted, i.e. how long
   a blob is guaranteed to survive. Keep it comfortably above the longest build and use the
   deployment's alert thresholds when classifying severity.
2. `get_cache_trends`: `CACHE_EVICTED` miss reason rate. If significant, storage is the bottleneck.
3. Operator-supplied hash-table **saturation rates** (not counts) — any sustained nonzero
   `putTooManyIterationsRate` or `getTooManyAttemptsRate` means the key-location map
   is silently dropping index entries; blobs stay on disk but become unreachable. These
   counters reset on restart, so a quiet dashboard right after a deploy proves nothing.

**Sizing guidance**:

| Signal | State | Recommendation |
|--------|-------|----------------|
| Eviction age < 1 hour | Critical | Grow the disk (and key-location map) now or add a storage shard |
| Eviction age 1-4 hours | Degraded | Increase disk by 50%; monitor trend |
| Eviction age 4-24 hours | Watch | Below the 24h alert threshold; plan growth |
| Eviction age > 24 hours and above your longest build | Healthy | No change needed |
| Any nonzero hash-table saturation rate | Key-location map undersized | Grow entries/`sizeMi` (bb-storage auto-rounds the count to a prime); grow the memory request for in-memory maps |
| High FindMissing rates | Clients re-checking existence | Enable existence caching on frontend |

**Key-location map sizing**: aim for **2-10x the expected live object count**
(`usable bytes / average blob size`; obtain a measured blob-size distribution from the operator).
In-memory maps cost ~64 bytes per entry of eagerly allocated heap;
on-disk maps ~66 bytes per record. **The map and the blocks are coupled: growing the disk
without growing the map makes eviction worse, not better.**

**Block configuration tradeoffs** (from analyze_buildbarn_storage, get_buildbarn_config, or supplied Jsonnet):
- `oldBlocks`: More = better least-recently-used approximation but more I/O overhead from
  copy-forward. Too few = first-in-first-out eviction. Typical: 8.
- `currentBlocks`: Majority of the device. More = larger stable storage. Typical: 24-30.
- `newBlocks`: Where writes land. Content Addressable Storage should use 3 (2-4 acceptable) to
  stagger expiration times. Action Cache (and ISCC/FSAC) **must** use 1 — bb-storage refuses
  to start mutable stores otherwise.
- `spareBlocks`: Buffer letting reads complete before block rotation. Typical: 3.

**Maximum blob size** = `blocks bytes / total_blocks` (the block size). If actions produce
larger outputs, uploads fail. Check the returned blob-size P99 against the block size.

> **Geometry changes flush persistent stores.** Changing `spareBlocks`/`oldBlocks`/
> `currentBlocks`/`newBlocks` or the blocks/device size changes the derived block size, and a
> persistent store discards ALL of its data on the next start. A store with an in-memory
> key-location map restarts empty regardless. Plan geometry changes as scheduled cache flushes.

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

---

## Worker Tuning

### Concurrency

The `concurrency` setting controls parallel actions per worker. Must match available CPU
and memory.

**How to assess**:
1. `get_worker_fleet_health`: CPU utilization per worker.
   - Consistently >85% → concurrency too high, actions contend for CPU.
   - Consistently <50% → concurrency too low, worker capacity wasted.
2. `list_buildbarn_events`: out-of-memory kills → concurrency × per-action memory exceeds limit.
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
2. get_worker_fleet_health: `input_root_population` stage timing
3. Native mode: check file cache size and `maximumCacheFileCount`
4. Virtual filesystem mode: check if prefetching is enabled in get_buildbarn_config

### Worker File Cache

- `maximumCacheFileCount`: Increase if actions have wide input trees.
- `maximumCacheSizeBytes`: Must accommodate the most common input files.
- **Signal cache is too small**: Input fetch times improve for repeated builds of the same
  targets but degrade when switching targets.
- **Invocation stickiness** on the scheduler helps by routing the same invocation's actions
  to the same workers, keeping file caches warm.

---

## Scheduler Tuning

### Platform Queue Management

The scheduler maintains separate queues per platform. Actions match to queues based on
platform properties (operating system family, container image, instruction set architecture).

**Diagnosing platform issues**:
1. `get_scheduler_health` shows per-platform breakdown
2. One platform with high queue depth while others are idle → that platform is under-provisioned
3. `platformQueueWithNoWorkersTimeout` (default 900 seconds) — queues with no workers are
   removed after this duration

**Platform identity is declared in several places and they must move together.** Matching is on the
exact property set, so a client-side change to any property value creates a different queue. When a
deployment updates a platform value, every one of these needs the same edit:

- the worker pool's advertised `platformProperties`
- any scheduler action-router or demultiplexing backend entry keyed on that platform (a stale key
  means the action falls through to the default router, losing that route's execution timeouts,
  invocation key extractors, and size-class config — and a `static` platform key extractor on the
  default route can silently send the work to an entirely different pool)
- any autoscaler query that selects on the serialized platform string; a stale selector reads zero
  queue depth forever, so the pool never scales up on demand

Two failure signatures distinguish a property mismatch from an image mismatch:

| Bazel outcome | Remote executions | Meaning |
|---------------|-------------------|---------|
| `REMOTE_ERROR` (exit 34) | zero | No worker advertises the requested platform. Nothing matched; no queue served it. |
| `BUILD_FAILURE` | nonzero | The platform matched and actions ran, then failed inside the worker's userspace. |

Watching `REMOTE_ERROR` flip to `BUILD_FAILURE` across a config rollout is the fingerprint of an
advertised property being bumped without the runner image being bumped with it. See the
`container-image` subsection under bb-runner in `REFERENCE.md` — the property is only a matching
key, never an image Buildbarn pulls.

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

### Autoscaling and Capacity Arrival

Diagnose capacity arrival from time-aligned evidence rather than from one peak.
For a known invocation with remote execution enabled:

1. Read a complete command line with `get_invocation(includeCommandLine=true)`
   and extract the last effective numeric `--jobs` value. `--jobs` is a client
   ceiling, not worker capacity.
2. Call `get_project` and read `data.completedActionLogEnabled`. If it is false,
   remote-action details and parallelism are unavailable; skip the next two
   action-data steps and do not interpret missing rows as zero.
3. Use `analyze_remote_execution` for invocation-owned queue totals,
   `queueWaitStats`, phase timing, and worker participation.
4. Use `get_build_parallelism(bucketSeconds=5)` for the executing remote-action
   ramp. It does not count queued/runnable work, replicas, or available slots.
5. Use `get_scheduler_health(invocationId=...)` when listed. Its padded project
   window may include other activity, so correlate rather than attribute.

| Pattern | Supported conclusion |
|---------|----------------------|
| Low executing parallelism + low queueing | Graph, lack of ready remote work, or a long action is likely limiting |
| Low executing parallelism + high queue duration/depth + few executing tasks | Scheduler/worker capacity is likely limiting |
| Long initial queue + fixed low concurrency plateau + later stepwise ramp | Capacity arrived late; slow autoscaling is plausible |
| One worker handles most actions while several others handle only a small tail | Later worker participation supports the late-capacity hypothesis |

The last two patterns do not prove autoscaler behavior. `list_worker_pools` is a
live desired/available snapshot, and remote-action worker rows show participation
only. Require historical desired/available replica, readiness, or controller
scale-event telemetry before stating that an autoscaler reacted slowly. If that
history is unavailable, label the conclusion medium confidence and recommend
instrumenting the scale decision, pod scheduling, image pull, and readiness
timeline separately.

---

## Diagnosing Infrastructure-Related Build Regressions

When builds get slower and the cause is not cache-related or code-related:

1. **Timeline correlation**: `summarize_infrastructure_health` for a slow build. Compare to the same
   tool for a recent fast build of the same targets.
2. **Storage**: `get_storage_health` → Did labeled operation rate change in the build window?
   Obtain separate verified eviction, latency, and error measurements before drawing those conclusions.
3. **Workers**: `get_worker_fleet_health` → Did labeled worker operation rate change?
   Obtain separate verified CPU, memory, and stage-timing measurements before drawing those conclusions.
   Use `list_buildbarn_events` for out-of-memory kills during the build window when listed.
4. **Scheduler**: `get_scheduler_health` → Queue depth growing? Specific platforms backed up?
5. **Network**: `get_grpc_health` → Error rates or latencies elevated between components?
6. **Configuration**: `get_buildbarn_config` → Has anything changed? Compare concurrency, storage
   sizes, and shard counts to what metrics suggest is needed.

---

## Infrastructure Scaling Decision Framework

| Metric | Threshold | Action | Expected Impact |
|--------|-----------|--------|-----------------|
| Queue wait 90th percentile > 10 seconds | Sustained over 1 hour | Add workers for affected platform | Reduces queue wait proportional to workers added |
| Eviction age < 4 hours | Sustained trend | Increase disk and key-location map together, or add a storage shard | Reduces `CACHE_EVICTED` misses |
| Worker CPU > 85% | Sustained during builds | Reduce worker concurrency or add workers | Reduces execution time variance |
| Worker memory > 80% | With out-of-memory kills | Increase worker memory limits | Eliminates out-of-memory action failures |
| Storage Get 90th percentile > 100 milliseconds | Sustained | Increase key_location_map; check disk I/O | Reduces input fetch and cache lookup times |
| Service mesh error rate > 1% | Any sustained period | Investigate specific error codes | Reduces action failures and retries |
| Fleet utilization < 30% | Sustained over 7+ days | Reduce fleet size or improve autoscaler | Reduces infrastructure cost |
