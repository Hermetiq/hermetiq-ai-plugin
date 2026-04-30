# Build Configuration Management

Since you cannot read users' `.bazelrc` files or BUILD files directly, infer build
configuration from Hermetiq telemetry and recommend improvements.

## Detecting Configuration from Invocation Data

Use ListInvocations (`time_range="7d"` or a user-requested window) to select representative
attempts, then call GetInvocation (`include_cmd_line=true`) to inspect effective configuration.
If the user gives an opaque ID, call ResolveBuildOrInvocation first and use the returned
`invocation_id` for invocation-level configuration checks.

- **Command-line flags**: Look for `--define`, `--copt`, `--action_env`,
  `--platform_suffix`, `--stamp`/`--nostamp`, `--incompatible_strict_action_env`,
  `--remote_download_minimal`, and `--jobs`.
- **Platform settings**: `platform_name` and `cpu` show the target platform. Remote execution
  and remote cache fields show which remote features are enabled.
- **Build tool version**: `build_tool_version` reveals the Bazel version.
- **User and host**: `user` and `host` identify who ran the build and from where.

## Configuration Drift Detection

Configuration drift is one of the most common causes of poor cache hit rates. Different
developers using different flags produce different action cache keys, fragmenting the cache.

How to detect drift from Hermetiq data:

1. **Cross-user flag comparison**: Use ListInvocations filtered by different users over the
   same `time_range`. Compare command-line arguments from GetInvocation. Differences in
   `--define`, `--copt`, or `--action_env` values cause cache fragmentation.
2. **CI versus local builds**: Filter ListInvocations by `role` or `host` to separate CI
   builds from developer builds. CI builds often represent the intended configuration.
3. **Branch-specific configuration**: Filter by `branch` to check whether feature branches use
   different build flags, such as debug versus optimized, that fragment the cache.
4. **Platform fragmentation**: Check whether different `--platform_suffix` values or remote
   execution properties are in use. Each distinct platform creates a separate cache partition.

Signals of configuration drift:

- `COMMAND_CHANGED` miss reason is a significant portion of total misses.
- Cache hit rates vary significantly between users building the same targets.
- Hit rates differ between CI and local builds.
- Different `build_tool_version`, `platform_name`, or `cpu` values appear for the same logical
  build across ListBuilds/ListInvocations results.

## Hermeticity Flag Audit

When cache hit rates are poor, verify these flags from invocation data. If a flag is missing,
recommend adding it to the project's shared `.bazelrc`:

| Flag | Purpose | How to Detect Absence |
|------|---------|----------------------|
| `--incompatible_strict_action_env` | Prevents environment variable leakage into actions | `ENV_CHANGED` miss reasons; different cache keys for identical code across machines |
| `--nostamp` | Disables volatile timestamp/git-SHA embedding | `INPUT_CHANGED` misses on stamped targets; volatile workspace status in command line |
| `--noexperimental_check_external_repository_files` | Avoids unnecessary re-fetching of external repos | Slow analysis phase; cache misses after repository fetch |
| `--experimental_remote_cache_compression` | Compresses Content Addressable Storage transfers | High input fetch and output upload times with moderate blob sizes |
| `--remote_download_minimal` | Only downloads outputs needed locally | High bytes received in build metrics; long output download phases |

## Remote Execution Flag Tuning

These flags affect remote execution performance. Recommend values based on observed metrics:

| Flag | What It Controls | How to Tune from Data |
|------|-----------------|----------------------|
| `--jobs=<N>` | Maximum concurrent actions | Compare to GetBuildParallelism peak. If parallelism plateaus below `--jobs`, the build graph is the bottleneck, not the job limit. If it hits `--jobs` consistently, increase it. Default for remote execution is 200. |
| `--remote_timeout=<seconds>` | Per-action timeout for remote execution | Check slowest actions in GetRemoteExecutionAnalytics. Set to 2-3x the slowest expected action. Default 3600 seconds is usually sufficient. |
| `--remote_retries=<N>` | Retry count for transient remote failures | Check action failure rates in GetGrpcHealth. If transient errors are common, increase from default 5. If errors are deterministic, retries waste time. |
| `--remote_default_exec_properties` | Default platform properties for remote actions | Check GetSchedulerQueueHealth per-platform breakdown. Ensure properties match worker platforms that have capacity. |

## Stamping Audit

Stamping is the single most common configuration mistake that kills cache performance. Stamped
actions embed volatile data, such as timestamps or Git SHAs, into outputs and invalidate every
downstream action's cache key.

How to detect stamping problems from Hermetiq data:

1. Look for `workspace_status_command` in invocation command-line arguments.
2. Check for `--stamp` or the absence of `--nostamp`.
3. Look for `INPUT_CHANGED` misses where the diff shows `input_root_digest` changed but the
   user made no meaningful source change.
4. Check whether cache miss patterns correlate with time-of-day rather than code changes.

Recommendation: use `--nostamp` as the default. Only enable `--stamp` for release builds via a
named configuration, such as `build:release --stamp`.

## Toolchain Version Management

Different toolchain versions produce different action cache keys. A single developer using a
different compiler version can fragment cache reuse for everyone.

How to detect toolchain drift:

1. `COMMAND_CHANGED` miss reasons where the command diff shows a different compiler path or
   version string.
2. Different `build_tool_version` values across users.
3. Cache hit rates that drop after toolchain updates and slowly recover.

Recommendation: pin all toolchains via Bazel's toolchain resolution. Prefer hermetic toolchains
downloaded by Bazel over system-installed tools.

## Configuration Recommendations Checklist

When auditing a project's configuration, systematically verify:

- [ ] `--incompatible_strict_action_env` is set
- [ ] `--nostamp` is the default, with stamping only for release builds
- [ ] No volatile `workspace_status_command` values propagate to non-release actions
- [ ] All users and CI share the same `.bazelrc` flags
- [ ] Toolchains are pinned, not system-installed compilers
- [ ] External repositories are pinned to exact versions
- [ ] `--remote_download_minimal` is enabled to reduce network transfer
- [ ] `--experimental_remote_cache_compression` is enabled to reduce storage transfer time
- [ ] `--jobs` is set appropriately for the observed worker fleet capacity
- [ ] Platform properties are consistent across the team
