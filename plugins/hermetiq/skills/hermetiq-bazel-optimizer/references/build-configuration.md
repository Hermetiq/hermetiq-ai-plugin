# Build Configuration Management

Since you cannot read users' `.bazelrc` files or BUILD files directly, infer build
configuration from Hermetiq telemetry and recommend improvements.

## Detecting Configuration from Invocation Data

GetInvocation returns command-line arguments, platform settings, and build metadata. Use these
to reconstruct the effective build configuration:

- **Command-line flags**: Visible in the invocation's command_line data. Look for `--define`,
  `--copt`, `--action_env`, `--platform_suffix`, `--stamp`/`--nostamp`,
  `--incompatible_strict_action_env`, `--remote_download_minimal`, `--jobs`.
- **Platform settings**: `platform_name` and `cpu` fields show the target platform.
  `remote_execution` and `remote_cache` flags show which remote features are enabled.
- **Build tool version**: `build_tool_version` reveals the Bazel version.
- **User and host**: `user` and `host` identify who ran the build and from where.

## Configuration Drift Detection

Configuration drift is one of the most common causes of poor cache hit rates. Different
developers using different flags produce different action cache keys, fragmenting the cache.

**How to detect drift from Hermetiq data**:

1. **Cross-user flag comparison**: Use ListInvocations filtered by different users over the
   same time period. Compare their command-line arguments. Differences in `--define`, `--copt`,
   or `--action_env` values cause cache fragmentation.

2. **CI versus local builds**: Filter ListInvocations by `role` or `host` to separate CI
   builds from developer builds. CI builds typically have the "correct" configuration. If
   local developer builds have different flags, those builds will miss the cache.

3. **Branch-specific configuration**: Filter by `branch` to check if feature branches use
   different build flags (e.g., debug versus optimized) that fragment the cache.

4. **Platform fragmentation**: Check if different `--platform_suffix` values or platform
   properties are in use. Each distinct platform creates a separate cache partition.

**Signals of configuration drift in the data**:
- `COMMAND_CHANGED` miss reason is a significant portion of total misses
- Cache hit rates vary significantly between users building the same targets
- Hit rates differ between CI and local builds

## Hermeticity Flag Audit

When cache hit rates are poor, verify these flags from invocation data. If a flag is missing,
recommend adding it to the project's shared `.bazelrc`:

| Flag | Purpose | How to Detect Absence |
|------|---------|----------------------|
| `--incompatible_strict_action_env` | Prevents environment variable leakage into actions | `ENV_CHANGED` miss reasons; different cache keys for identical code across machines |
| `--nostamp` | Disables volatile timestamp/git-SHA embedding | `INPUT_CHANGED` misses on stamped targets; volatile workspace_status in command line |
| `--noexperimental_check_external_repository_files` | Avoids unnecessary re-fetching of external repos | Slow analysis phase; cache misses after repo fetch |
| `--experimental_remote_cache_compression` | Compresses Content Addressable Storage transfers | High input fetch and output upload times with moderate blob sizes |
| `--remote_download_minimal` | Only downloads outputs needed locally (builds without the bytes) | High bytes received in BuildMetrics; long output download phases |

## Remote Execution Flag Tuning

These flags affect remote execution performance. Recommend values based on observed metrics:

| Flag | What It Controls | How to Tune from Data |
|------|-----------------|----------------------|
| `--jobs=<N>` | Maximum concurrent actions | Compare to GetBuildParallelism peak. If parallelism plateaus below `--jobs`, the build graph is the bottleneck, not the job limit. If it hits `--jobs` consistently, increase it. Default for remote execution is 200. |
| `--remote_timeout=<seconds>` | Per-action timeout for remote execution | Check slowest actions in GetRemoteExecutionAnalytics. Set to 2-3x the slowest expected action. Default 3600s (1 hour) is usually sufficient. |
| `--remote_retries=<N>` | Retry count for transient remote failures | Check action failure rates in GetGrpcHealth. If transient errors are common, increase from default 5. If errors are deterministic, retries waste time. |
| `--remote_default_exec_properties` | Default platform properties for remote actions | Check GetSchedulerQueueHealth per-platform breakdown. Ensure these match the worker platforms that have capacity. |

## Stamping Audit

Stamping is the single most common configuration mistake that kills cache performance.
Stamped actions embed volatile data (timestamps, git SHA) into their outputs, which
invalidates every downstream action's cache key.

**How to detect stamping problems from Hermetiq data**:
1. Look for `workspace_status_command` in invocation command-line arguments
2. Check for `--stamp` flag (or absence of `--nostamp`)
3. Look for `INPUT_CHANGED` misses where the diff shows `input_root_digest` changed but
   the user made no source code changes
4. Check if cache miss patterns correlate with time-of-day rather than code changes

**Recommendation**: Always use `--nostamp` as the default. Only enable `--stamp` for release
builds via a named configuration: `build:release --stamp`.

## Toolchain Version Management

Different toolchain versions produce different action cache keys. A single developer using
a different compiler version fragments the cache for everyone.

**How to detect from Hermetiq data**:
1. `COMMAND_CHANGED` miss reasons where the command diff shows a different compiler path
   or version string
2. Different `build_tool_version` values across users (different Bazel versions)
3. Cache hit rates that drop after a toolchain update and slowly recover

**Recommendation**: Pin all toolchains via Bazel's toolchain resolution. Use a hermetic
toolchain (downloaded by Bazel) rather than system-installed tools.

## Configuration Recommendations Checklist

When auditing a project's configuration, systematically verify:

- [ ] `--incompatible_strict_action_env` is set
- [ ] `--nostamp` is the default (stamping only on release builds)
- [ ] No volatile `workspace_status_command` values propagate to non-release actions
- [ ] All users and CI share the same `.bazelrc` flags
- [ ] Toolchains are pinned (not using system-installed compilers)
- [ ] External repositories are pinned to exact versions
- [ ] `--remote_download_minimal` is enabled (reduces network transfer)
- [ ] `--experimental_remote_cache_compression` is enabled (reduces storage transfer time)
- [ ] `--jobs` is set appropriately for the worker fleet capacity
- [ ] Platform properties are consistent across the team
