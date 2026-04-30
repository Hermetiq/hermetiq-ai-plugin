# Hermetiq Bazel Optimizer — Technical Reference

## Tool Call Constraints (Important)

- Prefer `ListBuilds` for user-facing build history because it groups multiple attempts by
  `build_id`. Use `ListInvocations` when you specifically need individual attempts.
- Use `ResolveBuildOrInvocation` when the user provides an opaque ID from a URL, copied text,
  or older permalink. It tells you whether to call build-level or invocation-level tools.
- `ListInvocations` does not return full command-line arguments. To audit flags, first select
  invocations with `ListInvocations`, then call `GetInvocation(include_cmd_line=true)` for each.
- `ListBuilds`, `GetBuildHistorySummary`, and `GetBuildTimeseriesAgg` filter through
  `invocation_filter`; use `BuildAggregationOptions` to choose match and rollup semantics.
- `GetFilters` excludes high-cardinality pattern values to keep filter loads bounded. Use
  `LookupPatternsForFilters(project_id, query)` for project-scoped pattern type-ahead lookups.
- Prefer stable aggregation tools (`GetRemoteExecutionAnalytics`, `GetRemoteActionTrends`) for
  transfer and timing bottlenecks before drilling into individual `FindRemoteActions` records.
- When prompt orchestration is unavailable in a client, use direct tool-call equivalents from
  the skill playbooks.

---

## Hermetiq Data Model

### Build
The logical build entity. One `build_id` can contain multiple invocations/attempts for retries,
reruns, or related upload flows. Build-level tools aggregate attempts by `build_id` and are the
right starting point for user-facing history, summaries, build detail pages, and trend cards.

Key build-level tools:
- `ListBuilds` — paginated logical build history grouped by `build_id`
- `GetBuild` / `GetBuildDetails` — one logical build and its attempts
- `GetBuildHistorySummary` — summary counts over a build universe
- `GetBuildTimeseriesAgg` — build-level counts over time
- `GetBuildTargetFastAnalytics` / `GetBuildTargetSlowAnalytics` — build-scoped target analytics

### Invocation (Attempt)
One per `bazel build|test|run|query` command execution. Use invocation-level tools when a
workflow needs a concrete attempt, per-action data, logs, command lines, tests, cache events,
remote execution analytics, or parallelism data.

Key fields for optimization analysis:
- `invocation_id` — one attempt
- `build_id` — logical build ID shared by related attempts when present
- `remote_cache_enabled` / `remote_execution_enabled` — Whether remote cache and remote execution were enabled
- `remote_cache_hits` / `total_executions` — Quick cache signal from the invocation summary
- `internal_executions` / `local_executions` / `remote_executions` — Execution strategy breakdown
- `disk_cache_hits` — Actions served from local disk cache without checking remote
- `critical_path_log` / `process_stats_log` — Raw critical path (the longest chain of sequential dependencies) and basic process stats logs (semi-structured text)
- `command` — Which Bazel command (build, test, run, cquery, aquery)
- `platform_name` / `cpu` — Target platform (affects cache partitioning)

### CacheEvent
One record per Action Cache lookup intercepted by Hermetiq's gRPC cache proxy.

Key fields:
- `hit` — Boolean; the most important field
- `action_mnemonic` — Action type (CppCompile, Javac, etc.)
- `digest_hash` / `digest_size` — Content-addressed action identifier
- `duration_micros` — Cache lookup latency
- `CacheMissAnalysis.reason` — Why the lookup missed when `include_miss_analysis=true`:
  - `NEVER_CACHED` — No prior cache entry exists for this action
  - `INPUT_CHANGED` — The action's input tree changed (most common)
  - `COMMAND_CHANGED` — The command line or flags changed
  - `ENV_CHANGED` — Environment variables affecting the action changed
  - `PLATFORM_CHANGED` — Platform requirements changed
  - `CACHE_EVICTED` — Entry existed but was evicted from storage
  - `PLATFORM_SUFFIX_CHANGED` — Platform configuration drift
  - `INSTANCE_MISMATCH` — Different remote cache instance
- `input_root_digest` / `command_digest` / `environment_hash` / `platform_hash` — Metadata
  used to determine miss reasons by comparing against previous hits

### RemoteAction
One record per action executed on a Buildbarn worker. Provides granular phase timing.

Key fields:
- **Phase timestamps** (all optional, presence depends on execution path):
  - `queued_at` to `worker_started_at` = queue wait
  - `input_fetch_started_at` to `input_fetch_completed_at` = input staging
  - `execution_started_at` to `execution_completed_at` = actual work
  - `output_upload_started_at` to `output_upload_completed_at` = result staging
- **Resource usage** (POSIX):
  - `resource_usage.user_time_nanos` / `resource_usage.system_time_nanos` — CPU time consumed
  - `resource_usage.block_input_operations` / `resource_usage.block_output_operations` — I/O operations
- `cost` — Normalized execution cost for this action
- `worker_node` / `worker_pod` — Which worker handled this action
- `cached_result` — Whether the result came from the remote Action Cache
- `mnemonic` / `target_id` — Action type and build target
- `output_file` — Output paths and digests

### BuildMetrics
Aggregate build-level metrics reported by Bazel itself (one per invocation).

Key fields:
- `actions_created` / `actions_executed` — Total action graph size versus what ran
- `action_cache_hits` / `action_cache_misses` — Bazel's own local Action Cache stats
- `analysis_duration` / `execution_duration` / `total_duration` — Build phase timing
- `cpu_duration` — CPU time
- `bytes_sent` / `bytes_received` — Network I/O during the build
- Content Addressable Storage operation metrics: `cas_operations`, `cas_operations_avg_ms`,
  `cas_remote_download*`, `cas_remote_upload*`

### ActionData
Per-mnemonic aggregated action statistics (one row per mnemonic per invocation).

Key fields:
- `mnemonic` — Action type
- `executed` / `created` — How many ran versus were in the graph
- `first_started_ms` / `last_ended_ms` — Temporal span of this mnemonic's executions

---

## Hermetiq Aggregated Analytics

### Build History (logical build grouping)
- `ListBuilds` — grouped build rows with primary invocation, attempt counts, status rollups,
  cache/execution totals, and pagination.
- `GetBuildHistorySummary` — total logical builds plus success, failure, interrupted, and
  in-progress counts over the selected build universe.
- `GetBuildTimeseriesAgg` — build counts bucketed by time with build-level status rollups.
- `BuildAggregationOptions.match_scope`:
  - `ANY_MATCHING_INVOCATION` — a build matches if any invocation matches the filters.
  - `LATEST_INVOCATION_ONLY` — a build matches based on its latest invocation only.
- `BuildAggregationOptions.rollup_scope`:
  - `MATCHING_INVOCATIONS_ONLY` — rollups summarize only matching invocations.
  - `ALL_INVOCATIONS_IN_SELECTED_BUILDS` — rollups include every invocation for selected builds.

### CacheEventAgg (per-invocation)
- `total_actions`, `hit_count`, `miss_count`, `hit_rate`
- `by_mnemonic` — Per-action-type breakdown
- `by_instance` — Per-cache-instance breakdown
- `top_miss_targets` — Targets with most misses
- `slowest_actions` — Highest cache lookup latency
- `by_miss_reason` — Count per reason category

### CacheTrends (cross-build, time-windowed)
- `summary` — Total lookups, hit rate, average latency over the period
- `buckets` — Per-day hit rates and lookup volumes
- `buckets.miss_reasons` — How miss reasons distribute over time
- `mnemonic_day_heatmap` — Mnemonic × day hit rate grid
- `top_miss_targets` — Targets with most misses over the period

### RemoteExecutionAnalytics (per-invocation)
- `total_cost`, `total_actions`, `total_execution_seconds`
- `unique_workers`, `unique_mnemonics`, `avg_parallelism`
- `stats` — Per-mnemonic phase breakdown (queue/fetch/execute/upload)
- `slowest_actions` — Top N by execution time
- `expensive_targets` — Top N by total cost
- `queue_wait_stats` — Per-mnemonic 50th/95th/99th percentile and max queue wait
- `io_hotspots` — Actions with highest block I/O
- `workers` — Per-worker action count and cost
- `cpu_efficiency_stats` — Per-mnemonic CPU utilization percentage
- `cache_miss_candidates` — Actions executed multiple times (same digest)
- `cache_summary` — Unique digests, repeated actions, potential savings

### RemoteActionTrends (cross-build, time-windowed)
- `summary` — Totals and period-over-period percentage changes for:
  wall_time, action_count, cost, cpu_time, build_count
- `buckets` — Action counts, costs, timing per day
- `mnemonics` — Distribution of action types
- `phase_breakdown` — Per-mnemonic average timing per phase
- `slowest_actions` — Top 50 across all builds
- `expensive_targets` — Top 50 across all builds
- `io_hotspots` — Top 50 by block I/O
- `cpu_efficiency` — Utilization percentage, user/system ratio, I/O-bound count
- `fleet_utilization` — Daily unique workers, churn (new versus returning), average actions/worker

### TargetTrends (cross-build, time-windowed)
- `summary` — total target runs, distinct targets, distinct invocations, success/failure counts,
  and total/average duration.
- `targets` — paginated per-target rows with kind, run count, invocation count, success/failure
  counts, total duration, and min/average/max duration.
- `GetTargetTrendDetail` — daily duration buckets and recent invocations for one target row.
- Use this when build duration or failures appear concentrated in a few targets, or when users
  ask which targets are getting slower over time.

### Project-Level Action and Activity Tools

These all take a `TrendsAggregatedRequest` (`project_id`, `time_range`, optional `filters` as a
`ListInvocationsRequest`) and return project-scoped rollups. `time_range` accepts `"7d"`, `"15d"`,
or `"30d"`.

- `GetProjectActivity` — high-level project activity counts and trends. Use for "how active is
  this project?" overview cards and for sanity-checking whether a project is still in use before
  recommending optimizations.
- `GetFailedActions` — top failed actions, daily failure counts, failure-detail breakdown,
  failure novelty, and aborted reasons. Use for project-wide failure pattern analysis when a
  single-build view (`FindActions(result_filter=ACTION_FAILED)`) is insufficient.
- `GetFlakyActions` — flakiest actions across the project. Loaded asynchronously by dashboards
  because the analysis is more expensive than the standard failure rollup. Use for the FLAKY
  bucket in test-failure investigations.

### Pattern Type-Ahead

- `LookupPatternsForFilters(project_id, query)` returns a bounded subset of Bazel patterns for
  type-ahead UIs. `GetFilters` intentionally excludes patterns due to their cardinality.

---

## Buildbarn Infrastructure Metrics (VictoriaMetrics)

These metrics come from VictoriaMetrics recording rules for Buildbarn components.
Queried via the infrastructure tools, scoped to a build's time window (±2 minute padding).

### Scheduler Metrics
- Queue depth over time (per platform)
- Task arrival and departure rates
- Queue wait time percentiles (50th, 90th, 99th)
- Retry distribution
- Per-platform breakdown

### Worker Fleet Metrics
- Operation rates (executions per second)
- Execution stage timing: queued, input-fetch, execution, output-upload
- CPU utilization (per worker, per platform)
- Memory utilization and pressure
- I/O throughput (block operations)
- File pool statistics

### Storage Metrics
- Operation rates by type: Get, Put, FindMissing
- Latency percentiles per operation type (50th, 90th, 99th)
- Error rates by operation
- Blob size distribution
- Disk eviction age (how long objects survive before eviction)
- Hash table occupancy and health
- Eviction rates over time

### Service Mesh Metrics
- Per-service request rates
- Error rates by gRPC status code
- Latency percentiles (50th, 90th, 99th)
- In-flight request counts
- Top error breakdown

### Cost Metrics (OpenCost)
- `node_total_hourly_cost` per worker node
- CPU, memory, GPU, persistent volume, and network cost breakdown
- Namespace-level cost aggregation
- Cost by controller (deployment or statefulset)

---

## Bazel Action Cache Mechanics

### How an Action Cache key is computed
An action's cache key is the hash of:
1. **Command line** — The exact command to execute (compiler path, flags, etc.)
2. **Input files** — Merkle tree hash of all declared input files
3. **Environment variables** — Only those explicitly declared by the rule
4. **Platform properties** — Execution platform constraints
5. **Output paths** — Declared output file names

If any of these change, the cache key changes and the lookup is a miss.

### Why hermeticity matters
A hermetic action depends only on its declared inputs. Non-hermetic actions read undeclared
state (environment variables, system files, timestamps) which changes the effective inputs
without changing the declared input hash. This causes:
- Cache misses when the same code runs on different machines
- Cache misses when the same code runs at different times
- Non-reproducible builds

### Common hermeticity violations
- `genrule()` that reads from `$HOME` or `/usr/local`
- Actions that embed `__DATE__`, `__TIME__`, or `__TIMESTAMP__`
- Toolchains that are not pinned (using system-installed compilers)
- `workspace_status_command` with volatile keys propagating to stamped actions
- Python rules with `import os; os.environ` in build-time scripts
- Actions that read the `.git` directory for version information

---

## Remote Execution Architecture

### Action lifecycle on Buildbarn
1. **Client submits** — Bazel sends Execute request to the scheduler
2. **Queued** — Scheduler places action in a platform-specific queue
3. **Dispatched** — Scheduler assigns action to an available worker
4. **Input fetch** — Worker downloads the input tree from Content Addressable Storage
5. **Execution** — Worker runs the command in a sandbox
6. **Output upload** — Worker uploads outputs to Content Addressable Storage
7. **Result cached** — Action Cache entry created for future lookups
8. **Client notified** — Bazel receives the result

### Where time is spent
- Steps 2-3 (queue): Depends on worker availability. Shows as queue_ms.
- Step 4 (fetch): Depends on input tree size and storage latency. Shows as input_fetch_ms.
- Step 5 (execute): Depends on action complexity. Shows as execution_ms.
- Step 6 (upload): Depends on output size and storage latency. Shows as output_upload_ms.

### Buildbarn concepts
- **Instance name**: Scopes the cache namespace (for example, per-project isolation).
  `hierarchicalInstanceNames: true` allows access to parent scopes.
- **Platform properties**: Key-value pairs that match actions to compatible workers
  (operating system family, container image, instruction set architecture, etc.)
- **Content Addressable Storage**: Stores all blobs (inputs, outputs) by content hash
- **Action Cache**: Maps action keys to result metadata (output digests)
- **Completeness checking**: Validates Action Cache entries reference blobs that still exist
  in Content Addressable Storage before returning them

---

## Buildbarn Architecture Deep Dive

### Component Architecture

**Request flow**: Bazel client → bb-storage frontend → two paths diverge:

1. **Storage path**: Frontend shards blob requests (Get, Put, FindMissing, ByteStream) across
   bb-storage backend shards by digest hash. Each shard holds a portion of all content.
   Frontend is stateless and horizontally scalable.

2. **Execution path**: Frontend forwards Execute requests to bb-scheduler (single instance),
   which maintains per-platform queues and dispatches to bb-worker instances. Each bb-worker
   downloads inputs from Content Addressable Storage, delegates sandboxed execution to an
   isolated bb-runner process, then uploads outputs back to Content Addressable Storage.

### bb-storage: The Storage Layer

#### Local Storage Backend
The primary on-disk backend (`LocalBlobAccess`) concatenates blobs into a large file or raw
block device, indexed by a **cuckoo hash table**. The hash table preferentially displaces
older entries, making it self-cleaning with no garbage collection.

**Block rotation model**: The storage device is divided into blocks that serve four roles.
Blocks rotate through these roles over time as data ages:

1. **Old blocks** (typical: 6-8): When a blob in an old block is read, it is copied forward
   to a new block. This implements pseudo least-recently-used eviction — frequently accessed
   blobs survive longer. Fewer old blocks makes eviction more first-in-first-out. More old
   blocks improves retention of hot data but increases copy overhead.
2. **Current blocks** (typical: 24-46): Stable storage. Should be the majority of the device.
   No copy-forward overhead for reads.
3. **New blocks** (typical: 1-4): Where new writes and copy-forward data land. Content
   Addressable Storage should use 2-4 to spread write load and stagger expiration. Action
   Cache needs only 1.
4. **Spare blocks** (typical: 3-4): Only used with raw block devices. Buffer so ongoing reads
   can complete before the underlying block is recycled.

**Key sizing formula**: `max_blob_size = device_size / total_blocks`

**Hash table configuration**:
- `keyLocationMapMaximumGetAttempts`: 16 (recommended). Controls hash slot probes before
  declaring a miss. Higher tolerates more collisions but slows lookups.
- `keyLocationMapMaximumPutAttempts`: 64 (recommended).
- Record count should be **prime** for optimal hash distribution.
- Can be stored in-memory (faster, lost on restart) or on block device (persistent).

**Persistence**: `minimumEpochInterval` controls fsync frequency. Default 300 seconds.
On SIGTERM, data is synced before shutdown.

#### Sharding
Distributes blobs across multiple storage backends by digest hash. Each shard has a `weight`
for proportional allocation.

**Topology options**:
- **Sharded only**: N shards, each holding 1/N of data. Losing one shard loses that fraction.
- **Mirrored only**: Two backends replicate everything. RAID-1 behavior.
- **Sharded + mirrored**: Each shard is mirrored. Enables rolling upgrades and single-node
  failure tolerance. Recommended for production.

**Replicator types** (for mirrored setups):
- `local`: Immediate client-side copy. Simple but can be slow under high concurrency.
- `queued`: Deduplicated queue with sequential execution. Better for high-write workloads.
- `concurrency_limiting`: Bounded concurrent requests. Prevents network saturation.

**Important**: Mirrored replication degrades heavily under high eviction rates. If eviction
is frequent, increase storage capacity before adding replication.

#### Completeness Checking
Wraps the Action Cache. Before returning an action result, validates all referenced output
blobs exist in Content Addressable Storage. Critical for builds without the bytes.

Configuration: `maximumTotalTreeSizeBytes` limits directory tree validation size.
Hermetiq uses 64 MB (development) / 256 MB (production).

#### Existence Caching
Caches blob existence checks to reduce round-trips. Useful when frontends handle high
FindMissingBlobs request rates from many concurrent Bazel clients.

#### Action Result Expiring
Forces periodic rebuilds by expiring Action Cache entries after a configurable duration.
Computed from `worker_completed_timestamp` with jitter to prevent rebuild storms.

### bb-scheduler: The Dispatcher

#### Queue Architecture
Maintains **platform queues** — separate queues for each unique combination of instance name
prefix and platform properties. Actions match to queues by their requested platform.

**Key parameters**:
- `platformQueueWithNoWorkersTimeout`: 900 seconds (15 minutes). Queues with no registered
  workers are garbage-collected after this duration.
- `defaultExecutionTimeout`: 1800 seconds (30 minutes). Maximum action execution time.
- `maximumExecutionTimeout`: 7200 seconds (2 hours). Hard ceiling.

#### Invocation Stickiness
Keeps workers assigned to the same Bazel invocation for a configured duration. Benefits:
file cache locality and reduced storage reads. Tradeoff: can cause load imbalance.

#### Size Class Routing
The **Initial Size Class Cache** stores per-action-type execution statistics. The scheduler
learns which worker size class is optimal per action type:
- Small compilations → small workers (cheaper)
- Large linking → large workers (faster)

#### Task Deduplication
Separates **operations** (client-visible, tied to invocations) from **tasks** (actual work).
If two concurrent builds request the same action, it executes only once.

#### Demultiplexing
Routes actions to different scheduling backends based on platform properties (for example,
container image). Hermetiq production uses this for multiple container environments.

### bb-worker: The Executor

#### Input Population Strategies

**Native (hardlinking)**:
Downloads all input files from Content Addressable Storage into a file cache, then hardlinks
into the build directory. Population time proportional to file count. Good when actions read
most of their inputs.

File cache parameters:
- `maximumCacheFileCount`: Hermetiq uses 10,000 (development) / 100,000 (production)
- `maximumCacheSizeBytes`: Hermetiq uses 1 GB (development) / 5 GB (production)
- `cacheReplacementPolicy`: Least recently used

**Virtual filesystem (FUSE or NFSv4)**:
Mounts virtual filesystem exposing input tree. Files fetched lazily on first read. Massively
reduces storage reads for over-specified actions. Requires privileged container mode.

**Prefetching** (companion to virtual filesystem):
Profiles which files actions actually access. Stores access patterns as Bloom filters. On
subsequent executions, pre-downloads predicted files in parallel. Workers spend <1% of time
fetching inputs with prefetching enabled.

#### Concurrency and Resource Management
- `concurrency`: Parallel actions per runner. Hermetiq uses 8 (development) / 11 (production).
- `inputDownloadConcurrency`: Parallel storage reads for input staging. Hermetiq uses 9-10.
- `outputUploadConcurrency`: Parallel storage writes for output staging. Hermetiq uses 11.
- `maximumFilePoolFileCount` / `maximumFilePoolSizeBytes`: Per-action temp file limits.

#### Directory Cache
In-memory cache for directory metadata objects. Reduces storage round-trips.
Hermetiq: 1,000 entries / 1 MB (development), 5,000 entries / 10 MB (production).

#### Completed Action Logging
Workers forward execution metadata to Hermetiq's analytics service via gRPC.
`maximumSendQueueSize`: 1,000 (buffers if the logger is temporarily unavailable).

### bb-runner: Execution Isolation
Two variants:
- **bb_runner_bare**: Expects tools pre-installed on the host.
- **bb_runner_installer**: Provides its own execution environment.

Worker ↔ runner communication uses gRPC over a Unix socket for security isolation.

### Hermetiq Production Configuration Reference

| Parameter | Development | Production | Notes |
|-----------|-------------|------------|-------|
| Content Addressable Storage disk size | 32 GB | 650 GB | 20x larger |
| Content Addressable Storage key_location_map | 400 MB | 800 MB | On block device |
| Content Addressable Storage old/current/new blocks | 8/24/3 | 6/46/2 | Production favors current blocks |
| Action Cache size | 20 MB | 5 GB | 250x larger |
| Action Cache key_location_map | 1 MB (disk) | 5M entries (memory) | Production uses in-memory for speed |
| Storage shards | 2 | 3 | Equal weight |
| Max tree size (completeness) | 64 MB | 256 MB | |
| Max message size | 2 MB | 10 MB | |
| Worker concurrency | 8 | 11 | |
| Worker file cache files | 10,000 | 100,000 | 10x |
| Worker file cache size | 1 GB | 5 GB | 5x |
| Worker directory cache | 1,000/1 MB | 5,000/10 MB | 5x/10x |
| Input download concurrency | 10 | 9 | Slightly reduced |
| Output upload concurrency | 11 | 11 | Same |
| Scheduler execution timeout | 1,800 seconds | 1,800 seconds | 30 minutes |
| Scheduler max timeout | 7,200 seconds | 7,200 seconds | 2 hours |
| Queue no-workers timeout | 900 seconds | 900 seconds | 15 minutes |
| Tracing | Disabled | 25% sample rate | To OpenTelemetry collector |
| Scheduler routing | Simple | Demultiplexing | Multi-container platform support |

### VictoriaMetrics Recording Rules

Hermetiq creates 50+ recording rules for Buildbarn metrics:

**Storage rules**:
- `bb:blobstore_blob_access_operations_started` — Operation count by type and backend
- `bb:blobstore_blob_access_operations_duration_seconds_bucket` — Latency distribution
- `bb:blobstore_local_blob_access_key_location_map_*` — Hash table health
- `bb:blobstore_local_blob_access_old_current_new_*` — Block insertion timing

**Scheduler rules**:
- `bb:scheduler_in_memory_build_queue_tasks_*` — Queue depth (queued/executing/completed)
- `bb:scheduler_in_memory_build_queue_tasks_executing_duration_seconds_*` — Execution timing
- `bb:scheduler_in_memory_build_queue_tasks_executing_retries_*` — Retry distribution

**Worker rules**:
- `bb:worker_virtual_execution_duration_seconds_*` — Action execution timing
- `bb:worker_posix_resource_usage_*` — CPU, memory, I/O resource metrics
- `bb:worker_file_pool_*` — Temp file pool statistics
- `bb:worker_input_root_population_*` — Input staging timing

**Service mesh rules**:
- `bb:grpc_server_handled_total` / `bb:grpc_client_handled_total` — Request rates
- `bb:grpc_server_handling_seconds_bucket` — Latency distribution
- `bb:grpc_server_msg_sent_total` / `bb:grpc_server_msg_received_total` — Message rates

---
