# Buildbarn Infrastructure Tuning Reference

Use `summarize_infrastructure_health` first for live infrastructure health, and
use `analyze_buildbarn_storage` or `get_buildbarn_config` when available to read
live configuration. If neither live configuration tool is present in `tools/list`
and neither the user nor the host named a ConfigSet as the deployed source, ask
the operator for the relevant Jsonnet/ConfigMap content rather than choosing a
saved ConfigSet or substituting runtime metrics.

Infrastructure scope comes from the Project's Managed Namespace in both Cloud
and on-prem; use the exact server-resolved namespace and deployment/operator
context (`infrastructure.namespace`, `telemetryScope`, `deploymentMode`,
`operator`, `callerIsOperator` when present on the envelope). Namespace metrics
cover all clients using those resources, even with one registered project.
Project analytics remain separate. Keep this scope explicit in tuning findings,
and direct shared-resource changes to the installation operator unless server
context establishes caller authority.

---

## Infrastructure Health Verdicts and Symptom Triage

Start with `summarize_infrastructure_health` scoped to the invocation time window
(`invocationId`), a relative `timeRange` (`"1h"`, `"24h"`, `"7d"`), or explicit
RFC 3339 `startTime` and `endTime`. Each component returns its own `assessment`
plus an `assessmentReason` naming the rows, values, and thresholds used;
`get_scheduler_health`, `get_worker_fleet_health`, `get_storage_health`, and
`get_grpc_health` return the same pair. Always quote `assessmentReason` alongside
the verdict, and drill into a component's tool only when its verdict is not
`healthy`.

| Component | Assessment values |
|-----------|-------------------|
| Storage, gRPC | `healthy`, `degraded`, `critical` |
| Scheduler | `healthy`, `scaling_lag`, `tail_latency`, `congested`, `saturated`, `stalled` |
| Workers | `healthy`, `idle`, `stressed`, `overloaded` |

Any component may return `no_data`, which means telemetry is absent — never idle
or healthy. The summary's overall `assessment` maps the worst component onto one
shared scale:

| Overall | Component verdicts |
|---------|--------------------|
| `critical` | storage or gRPC `critical` (errors above 5%), workers `overloaded`, scheduler `stalled` |
| `degraded` | scheduler `saturated`, `congested`, `tail_latency`, or `scaling_lag`; workers `stressed`; storage or gRPC `degraded`; any component with `no_data` |
| `healthy` | `healthy`, `idle` |

### Scheduler Pair Verdicts and `scaleUp`

The scheduler judges queue waits per platform/size-class pair in
`platformAssessments[]` (or fleet-wide waits when unlabeled). Queue depth
(`scheduler_queue_depth`, `queueDepthPeak`) is context only; a burst that queues
hundreds of actions and drains quickly on short waits is `healthy`.

| Pair verdict | Rule |
|--------------|------|
| `stalled` | Queued work persisted through a 10-minute stretch in which nothing executed for the pair |
| `saturated` | p90 wait above 120 s, or queued work persisted through a 10-minute stretch while work executed |
| `congested` | p90 wait above 60 s |
| `tail_latency` | p99 wait above 60 s with p90 at or below 60 s |
| `scaling_lag` | A `tail_latency` alongside a serving pool scaling up within 10 minutes and below its slot ceiling; co-occurrence does not prove scale-up caused the wait |
| `healthy`, `idle` | Anything else; `idle` when nothing was queued or executed |

Each pair names its serving `pool`, `backlogExcess` (actions queued through a
10-minute stretch), and `capacityLimited` (whether sampled `executingPeak`
reached `slotCeiling`, computed from serving pools' `maxReplicas` or fixed
replicas times concurrency). Whenever a serving pool's ready replicas trailed a
rise in desired replicas, the pair carries `scaleUp` (`readyLagMedianSeconds`,
`readyLagMaxSeconds` at `stepSeconds` resolution, `slow` when max lag exceeds
10 minutes, and pod event `phases` when available, with `podsTruncated` when
sampled).

### Fleet Activity and Metric Aggregation Rules

- **`activity` on `summarize_infrastructure_health`:**
  - `mostly_idle`: executing actions averaged under half the worker slots
    (`slotUtilization` = `executingAverage / slotsAverage`) or, when slots are
    unmeasured, most samples had nothing queued or executing (`idleShare`).
  - `capacity_limited`: replaces `mostly_idle` when at least one pool ran at its
    slot ceiling with queued work in 5 or more one-minute samples
    (`capacityLimitedPools` and `reason` name the pools, peak, ceiling, queue
    depth, and saturated minutes). Never read `capacity_limited` as spare
    capacity, and check `platformAssessments[].capacityLimited` even on a
    `mostly_idle` window (which only rules out saturation of 5+ minutes).
  - `active` or `unmeasured` otherwise. Report `activity` alongside the verdict,
    never in place of one.
- **Idle vs. stuck workers:** `idle` means zero worker throughput with an empty
  scheduler queue. Zero throughput while `scheduler_queue_depth` is non-empty
  reports `stressed` (a stuck fleet); `assessmentReason` states which case held.
- **Near-idle gRPC error rates:** On a quiet component, one `ResourceExhausted`
  over a few dozen calls exceeds 1% and triggers `degraded`. Always quote
  absolute counts from `server_handled` alongside `server_error_rate_pct`.
- **Never compare different `aggregation` values:** Every metric row carries
  `unit` and `aggregation` (`peak`, `average`, `instant`, `minimum`, `total`, or
  `derived`). Compare `peak` rates only with `peak` rates and `average` latencies
  only with `average` latencies.
- **Invocation-scoped windows are shared:** Infrastructure tools called with
  `invocationId` query a padded project window that includes other concurrent
  builds. `list_worker_pools` and `list_rbe_workers` are current snapshots, never
  historical replica counts for an earlier invocation.

### Symptom Triage Table

| Symptom | Tool | Metric to check | Action |
|---------|------|-----------------|--------|
| High queue time | `get_scheduler_health` | `queue_duration_{p50,p90,p99}`, `platformAssessments[]` (`backlogExcess`, `capacityLimited`, `scaleUp`), `retries_*`, `queued_rate`, `executing_rate`, `completed_by_code`, `platform_breakdown`; `scheduler_queue_depth` as context | `stalled`: check why no worker served the pair (`list_worker_pools`, `list_rbe_workers`). For `congested`, `saturated`, `tail_latency`, or `scaling_lag`, correlate queue growth with replica and event timelines before attributing waits to capacity arrival |
| Autoscaler errors or Warning events | `list_worker_pools` | `scaledObject.conditions`, `scaledObject.scalingActive`, `unavailableSince`, `snapshotAt`, `scaledObjects` | Act on a condition that has persisted 10 minutes or more; scheduling and KEDA reconcile Warning events alone are transient |
| Suspected late capacity | `get_scheduler_health` (`scaleUp`), then `get_worker_scaling_timeline` | `scaleUp` lag and phases; time-aligned `desired`, `available`, and `ready` replicas over the invocation window; scale-event coverage | Confirm whether replicas became ready after queue growth; absent/incomplete series keep autoscaling as a hypothesis |
| Unknown deployment topology | `get_buildbarn_status` | `data.status`, `data.assessment`, `data.chart`, `data.storageShards`, per-component `role`/`kind`/`readyReplicas`/`images` | Establish deployed topology before reading metrics; `storageShards` separates real storage shards from worker-local cache series |
| Storage load or slow serving | `get_storage_health` | `data.assessment`, `eviction_age_min_shard`, `<type>_latency_*`, `<type>_error_rate_pct`, `hash_*`, `<type>_operations_by_op`, `device_*` | Examine storage error rates, latency, and hash-table pressure before proposing sizing changes |
| Worker resource pressure | `get_worker_fleet_health` | `execution_stage_{p50,p90,p99}`, `rss_p90`, `cpu_{user,system}_p90`, `block_io_{in,out}_p90`, `*_ctx_switches_p90`, `file*_p90`, `scheduler_queue_depth` | Tune worker sizing or concurrency |
| gRPC errors | `get_grpc_health` | `server_error_rate_pct`, `top_codes`, `{server,client}_latency_*`, `{server,client}_in_flight` | Investigate service/network failures; latency percentiles exclude the `buildbarn.remoteworker.OperationQueue` long poll unless `serviceFilter` names it |
| Pod restarts or out-of-memory | `list_buildbarn_events`, `get_buildbarn_pod_logs` | `newest_first` records, `hasMore`/`nextOffset`, `omittedFields` (`includeAllFields=true` for full record) | Page with frozen `startTime`/`endTime` or `invocationId`; adjust memory limits or concurrency |
| Remote actions fail for one toolchain with loader/exec errors | `find_remote_actions`, `get_remote_action_command` | Failed vs. succeeded mnemonics, distinct `workerPod` values, requested `container-image`, `list_rbe_workers` `runnerImage` | Run the Remote Execution Environment Mismatch Playbook below |
| Storage config audit / sizing | `analyze_buildbarn_storage`, `get_buildbarn_config` | `data.configurationFiles`, `data.configurations`, `data.geometry`, secret-bearing keys, `data.findings` | Run the Storage Configuration Audit Playbook below |
| General config inspection | `get_buildbarn_config` + schema tools | Storage, scheduler, and worker protobuf fields | Resolve message FQNs before calling `describe_buildbarn_config_type` |

---

## Storage Tuning and Configuration Audit

### Storage Configuration Audit Playbook

1. **Discover mounted configuration and geometry:** Call
   `analyze_buildbarn_storage` without `store` to discover which files installed
   Buildbarn workloads mount or read (`data.configurationFiles`), secret-bearing
   keys, and `data.findings`.
   - Read `data.scope` (`mounted_only` by default; pass `includeUnmounted=true`
     only when inspecting orphaned ConfigMap generations), `data.scopeReason`,
     and each entry's `mounted` field (`mounted`, `unmounted`, or `unknown`).
   - Take the `CAS`/`AC`/`ISCC`/`FSAC` store mapping from
     `data.configurations[].stores` and `data.configurations[].fields`, never
     from filename substrings or user labels (`store` filters semantic
     configuration fields, not filenames).
   - Read `data.geometry.status`, `reason`, and each `data.geometry.stores[]`
     entry's `status`: quote `blockSizeBytes`, `usableCapacityBytes`, and
     `maximumBlobSizeBytes` with `data.geometry.sectorSizeAssumption` only for
     `computed` entries. `device_size_unknown` requires the operator's raw device
     size; `invalid` means a layout `bb-storage` rejects. Empty `findings` does
     not prove configuration correctness or adequate sizing.
   - Call `get_buildbarn_config(component=...)` using the bare file key (e.g.,
     `storage.jsonnet`) to inspect key-location-map sizing and other settings.
   - When `analyze_buildbarn_storage` is absent from `tools/list`, check whether
     `get_buildbarn_config` is listed (`component="storage"` and `"frontend"`),
     and read `buildbarn://guides/storage-model` when MCP resource retrieval is
     available. If both live Kubernetes tools are absent and no ConfigSet is
     explicitly identified as the deployed source, make **no MCP calls** and
     report active configuration access unavailable.
   - When using schema tools, prefer `get_buildbarn_config_field` for a known
     path, `search_buildbarn_config_schema` for discovery,
     `describe_buildbarn_config_type` for one type, and
     `list_buildbarn_config_roots` for service roots. A field's reported type is
     a bare message name without package, so resolve a full `fqn` from
     `nested_message.fqn` at `depth >= 1` or via `search_buildbarn_config_schema`
     before calling `describe_buildbarn_config_type`.
2. **Corroborate with runtime health:** When `get_storage_health` is listed, call
   `get_storage_health(timeRange="24h")` (or the requested window, optionally
   filtered by `storageType`: `"cas"`, `"ac"`, `"iscc"`, or `"fsac"`). If absent,
   state that runtime health is unavailable.
3. **Verify persistence and geometry before recommending changes:**
   - If geometry must be derived manually from complete config and device-size
     evidence: `blockSize = floor(blocksBytes / sectorSize / totalBlocks) * sectorSize`,
     and `usableCapacity = blockSize * (oldBlocks + currentBlocks + newBlocks)`.
     One block is the maximum storable blob.
   - A store survives restarts only when all three pieces persist together: the
     blocks, the key-location map, and the `persistent` state directory. Verify
     mounts, backing storage, and lifecycle for all three; an in-memory map is
     process-local.
   - Changing block counts or device size changes the derived block size and
     causes a persistent store to **discard all existing data on next start** —
     treat geometry changes as planned cache flushes.
   - Resolve exact schema paths before naming configuration fields (for block
     device write limits: `blocksOnBlockDevice.source.writeConcurrencyLimit`,
     where `0` means no configured cap on concurrent write syscalls;
     `maximumMessageSizeBytes` caps unmarshaled Protobuf messages, not whole
     ByteStream blobs).
4. **Preview or apply with ConfigSets (when enabled):** Use `render_config_file`
   and `diff_config_set_commits` to preview changes; require explicit user
   authorization and confirmation before calling `save_config_set`.
5. **Report per store:** State observed facts, evidence-backed issues with
   confidence, and exact configuration fields and current values. When evidence
   is insufficient, state that sizing and the need for a change remain unproven.

### `get_storage_health` Metrics and Reading Rules

`data.assessment` (`healthy`, `degraded`, `critical`, or `no_data`) is derived
from the highest `<type>_error_rate_pct` among active stores and
key-location-map pressure. `evictionActivity` and `retentionAssessment` remain
unknown without a discard counter or timestamp.

| Metric | Unit & Aggregation | Meaning |
|--------|--------------------|---------|
| `operation_rate`, `<type>_operation_rate` | `ops_per_second`, `peak` | Blob-access operations across all stores or per store (`cas_`, `ac_`, `iscc_`, `fsac_`) |
| `<type>_operations_by_op` | `ops_per_second`, `peak` | Split by `labels.operation` (`Get`, `Put`, `FindMissing`); `Get` counts only hits |
| `<type>_latency_{get,put,findmissing}_{p50,p90,p99}` | `milliseconds`, `average` | Per-operation latency (`ISCC` and `FSAC` serve only `Get` and `Put`) |
| `<type>_error_rate_pct` | `percent`, `derived` | Excludes `NotFound`, `Canceled`, `AlreadyExists` (`NotFound` is a normal miss) |
| `<type>_operation_count`, `<type>_error_count` | `ops_per_second`, `average` | Numerator and denominator behind the error rate |
| `iscc_get_found_pct`, `fsac_get_found_pct` | `percent`, `derived` | `OK / (OK + NotFound)` lookup hit share; lookup outcome only, never an error or sizing signal |
| `eviction_age_min_shard` | `hours`, `derived` | Minimum shard insertion age of the last discarded block (`eviction_age` can include non-shard local caches). Historical insertion-age context only, not current retention |
| `cas_blob_size_{p50,p90,p99}` | `bytes`, `bucket_bound` | Histogram bucket boundary (`lowerBound` and `upperBound`), **not** an interpolated size or mean |
| `cas_blob_size_buckets` | `count`, per `le` | Cumulative blob-size histogram |
| `hash_{get_too_many_attempts,put_too_many_iterations}` | `ops_per_second`, `peak` | Sampled peak of key-location-map probe exhaustion; indicates pressure occurred in the window, not sustained occupancy or a new map size |
| `eviction_set_ops` | `ops_per_second`, `instant` | Cluster-wide eviction-set rate (per-second rate despite the `rate1h` recording-rule lookback name) |
| `device_io_utilization`, `device_write_latency`, `device_write_throughput`, `device_queue_depth` | node-level | Shared node disk metrics for nodes hosting storage pods (not store-isolated) |

**Block and Key-Location Map Tradeoffs:**
- `oldBlocks` (typical: 8): reads copy blobs forward to `newBlocks` (pseudo-LRU).
- `currentBlocks` (typical: 24–30): stable storage with no copy-forward overhead.
- `newBlocks`: writes land here. CAS uses 3 (2–4); mutable stores (`AC`, `ISCC`,
  `FSAC`) **must use 1** or `bb-storage` refuses to start.
- `spareBlocks` (typical: 3): buffer so ongoing reads finish before rotation.
- **Key-location map:** `keyLocationMapMaximumGetAttempts` (recommended: 16) and
  `keyLocationMapMaximumPutAttempts` (recommended: 64). In-memory maps use ~64 B
  per entry; on-disk maps use ~66 B per record. Coupling: expanding block
  storage increases live object counts, so evaluate map headroom alongside disk
  changes.

---

## Worker and Scheduler Tuning

### Worker Concurrency, File Cache, and Input Population

- **Concurrency (`concurrency`):** Parallel actions per worker (`vCPU count - 1`
  is a typical starting point for CPU-bound work). In `get_worker_fleet_health`,
  `cpu_user_p90` and `cpu_system_p90` are per-action CPU seconds, **not**
  utilization percentages, and `rss_p90` is single-action peak RSS (capped at
  4 GiB), not container memory. Check `list_buildbarn_events` for out-of-memory
  kills (`concurrency × per-action memory > container limit`).
- **Input population strategies:**
  - *Native (hardlinking)*: downloads all inputs into a local LRU file cache
    (`maximumCacheFileCount`, `maximumCacheSizeBytes`).
  - *Virtual filesystem (FUSE/NFSv4) + FSAC prefetching*: fetches files lazily
    and pre-downloads predicted access profiles in parallel.

### Platform Queue Management

Matching between an action's requested platform and a worker pool's advertised
platform is **exact string equality** on the marshaled, lexicographically sorted
`platformProperties` (`platformQueueKey` in `list_rbe_workers`). When updating a
platform property value, update all three places together:
1. Worker pool advertised `platformProperties`.
2. Scheduler action-router / demultiplexing entries keyed on that platform.
3. Autoscaler (KEDA/Prometheus) queries selecting on the serialized platform string.

| Bazel outcome | Remote executions | Meaning |
|---------------|-------------------|---------|
| `REMOTE_ERROR` (exit 34) | `0` | General remote failure; proves no compatible worker matched only when combined with an explicit no-workers failure message and the requested platform |
| `BUILD_FAILURE` | `> 0` | Actions matched and ran before failing; inspect stderr for compiler/test errors vs. userspace loader errors |

### Remote Execution Environment Mismatch Playbook

Use this playbook when remote actions fail with dynamic loader or interpreter
errors (`version 'GLIBC_x.y' not found`, `cannot open shared object file`,
`cannot execute binary file`, missing ELF interpreter, or missing
`/usr/bin/env python3`). **Do not use this playbook when stderr is empty and
`data.aggregations` shows `DEADLINE_EXCEEDED` with a uniform `durationStats`
clamp or `supersededBySuccessfulAttempt: true` (that is a size-class timeout).**

1. **Confirm invocation status and failure class:** Call `get_invocation` and
   record `status`, `exitCode`, `exitCodeName`, and `failureMessage`.
2. **Partition failed vs. succeeded mnemonics:** Call
   `find_remote_actions(result="failed")` and `find_remote_actions(result="success")`,
   and check `get_invocation(includeActionSummary=true)`. Failures confined to
   one toolchain's mnemonics (e.g., `CppCompile`) while others (`Javac`,
   `GoCompile`) succeed remotely is the userspace mismatch signature. Failures
   across unrelated mnemonics point to fleet, storage, or network issues.
3. **Rule out a single bad node:** Check distinct `workerNode`/`workerPod` values
   on failed remote actions. Many pods in a pool = pool image/config issue; one
   pod = node drift (inspect `list_buildbarn_events` and `get_buildbarn_pod_logs`).
4. **Check the requested command and toolchain hermeticity:** Call
   `get_remote_action_command` on a failed action digest. Record
   `data.command.platform.properties` (including `container-image`) and the
   failing executable path:
   - Path under `external/` (e.g., `external/llvm_toolchain_llvm/bin/clang`):
     staged from the repo's toolchain pin — the toolchain outran the worker
     runner image; upgrade the runner image rather than downgrading the toolchain.
   - System path (e.g., `/usr/bin/gcc`): supplied by the runner image.
5. **Check the actual runner image:** Buildbarn **never pulls** the
   `container-image` platform property; actions run in the pool's **runner**
   container image. Call `list_rbe_workers` or `get_rbe_worker` to read
   `runnerImage` and `imagePlatformPinning` (do not guess the runner from the
   mixed `list_worker_pools.images` array). Compare the runner OS/glibc floor
   against the required symbol (see the glibc table in `references/REFERENCE.md`).
   Because worker tools are current snapshots, confirm for older invocations
   whether the image changed since the build.
6. **Find the regression boundary:** Use `list_builds` filtered to the
   repository to locate the last passing build and commit delta. A rollout that
   shifts from no-worker `REMOTE_ERROR` (0 remote executions + no-matching-worker
   message) to loader `BUILD_FAILURE` (>0 remote executions + loader stderr)
   indicates the advertised property was bumped without updating `runnerImage`.
7. **Report:** State the requested platform, actual `runnerImage`, missing symbol
   or interpreter, which side is stale, and all three places platform identity
   must move together (worker `platformProperties`, scheduler routes, autoscaler
   selectors).

### KEDA Autoscaling and `scaleUp` Phase Investigation

For single-invocation capacity arrival diagnostics, follow the canonical **Slow
Build or Known Invocation Flow** in `SKILL.md`.

Judge live autoscaler health from `list_worker_pools`, not Kubernetes Warning
events alone. A condition requires action only when it has persisted at least
**10 minutes** by `snapshotAt`:
- An unavailable pool, aged by `unavailableSince`.
- HPA `scalingActive` False for `FailedGetExternalMetric` or
  `FailedGetObjectMetric`, aged by `lastTransitionTime`.
- KEDA `ScaledObject` in `Fallback`, aged by `metricFailures × 15 s` (HPA reads
  every 15 s by default; `Fallback` without `metricFailures` still needs
  attention).
- `scaledObjects` status `not_permitted` or `error` leaves unreadable autoscaler
  state unknown (not healthy); `unavailable` means KEDA is not installed.
- KEDA `Ready` False alone, `FailedScheduling` during node scale-up, and KEDA
  reconcile warnings are transient unless corroborated by pool waits or
  unavailability.

When `get_scheduler_health` returns `platformAssessments[].scaleUp`, report
`readyLagMedianSeconds` and `readyLagMaxSeconds` with `stepSeconds` resolution
and each phase's pod count (`nodeWaitMedianSeconds`, `imagePullMedianSeconds` /
`slowestImage`, `startupMedianSeconds`). These medians cover different pod
populations and are investigation leads rather than a partition of ready lag:

| Phase | Investigation lead | Possible remedies when corroborated |
|-------|--------------------|-------------------------------------|
| Node wait (`nodeWaitMedianSeconds`) | Pod scheduling or node supply delay | Warm node headroom (overprovisioning pause pods or node-pool minimum) or higher pool `minReplicas` |
| Image pull (`imagePullMedianSeconds`, `slowestImage`) | Runner image pull delay | Pre-pull DaemonSet, cloud node-image/secondary-disk preload, regional registry with lazy/streamed pulls, or slimmer runner image |
| Startup (`startupMedianSeconds`) | Includes image pulls plus init/container startup | Inspect init containers and readiness in `list_buildbarn_events` and `get_buildbarn_pod_logs` |

---

## Infrastructure Scaling Decision Framework

| Signal | Condition | Action |
|--------|-----------|--------|
| Scheduler `congested` or `saturated` | Queue waits exceed server thresholds | Align queue, replica (`get_worker_scaling_timeline`), and event timelines before proposing capacity changes |
| Eviction insertion age (`eviction_age_min_shard`) | Any value | Historical insertion age only; establish actual discard activity and cache reuse intervals before sizing |
| Action CPU / memory pressure | High `rss_p90` with OOM events in `list_buildbarn_events`, or high `cpuPerRunningSecond` with contention | Adjust worker memory limits or `concurrency` |
| Storage `Put` / `Get` latency elevation | Time-aligned across comparable windows | Compare store latency, `device_write_latency`, `device_io_utilization`, and `hash_*` pressure before changing shards or write limits |
| Service mesh `server_error_rate_pct > 1%` | Sustained with non-trivial `server_handled` volume | Inspect `top_codes` and component logs |
| Low fleet `activity.slotUtilization` | `activity` is `mostly_idle` (not `capacity_limited`) across representative peak windows | Review `minReplicas` and demand peaks; do not claim dollar savings without `get_cost_summary` |
