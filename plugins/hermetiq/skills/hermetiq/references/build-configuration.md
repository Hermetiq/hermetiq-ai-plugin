# Build Configuration Management

Since you cannot read users' `.bazelrc` files or BUILD files directly, infer build
configuration from Hermetiq telemetry and recommend improvements.

## Detecting Configuration from Invocation Data

Use `list_invocations(lookback="7d")` or a user-requested supported window to select
representative attempts from `data.invocations[]`, then call
`get_invocation(invocationId=..., includeCommandLine=true)` to inspect effective
configuration under `data.invocation` and `data.commandLine`. If the user gives
an opaque ID, call `resolve_build_or_invocation` first and use the returned
`data.invocationId` for invocation-level configuration checks.

- **Command-line flags**: Look for `--define`, `--copt`, `--action_env`,
  `--platform_suffix`, `--stamp`/`--nostamp`, `--incompatible_strict_action_env`,
  `--remote_download_minimal`, and `--jobs`.
- **Platform settings**: `platformName` and `cpu` show the target platform. Remote execution
  and remote cache fields show which remote features are enabled.
- **Outcome**: read `data.invocation.status` — always present, one of `success`, `failed`,
  `interrupted`, `in_progress`, `unknown` — never `exitCode`, which is absent rather than 0
  when the backend recorded none. When comparing a drifted configuration against a working
  one, exclude `unknown` invocations rather than counting them as successes.
- **Build tool version**: `data.invocation.buildToolVersion` reveals the Bazel
  version. Parse its major version and apply the Bazel 5–9 compatibility matrix
  in `bazel-optimization.md` before recommending a flag. If it is unavailable,
  unparseable, or outside that range, ask for the version or ask the user to
  verify the candidate with `bazel help build --long`; do not guess a spelling.
- **User and host**: `user` and `host` identify who ran the build and from where.

## Configuration Drift Detection

Configuration drift is one of the most common causes of poor cache hit rates. Different
developers using different flags produce different action cache keys, fragmenting the cache.

How to detect drift from Hermetiq data:

1. **Cross-user flag comparison**: Use `list_invocations` over one `lookback`, select returned
   attempts from the users being compared, and inspect each with `get_invocation`. Differences
   in `--define`, `--copt`, or `--action_env` values cause cache fragmentation.
2. **CI versus local builds**: Select representative returned attempts by their user/host
   evidence; these are result fields, not `list_invocations` filters. CI builds often represent
   the intended configuration.
3. **Branch-specific configuration**: Use the public `branch` filter to check whether feature branches use
   different build flags, such as debug versus optimized, that fragment the cache.
4. **Platform fragmentation**: Check whether different `--platform_suffix` values or remote
   execution properties are in use. Each distinct platform creates a separate cache partition.

Signals of configuration drift:

- `COMMAND_CHANGED` miss reason is a significant portion of total misses.
- Cache hit rates vary significantly between users building the same targets.
- Hit rates differ between CI and local builds.
- Different build-tool version, platform, or CPU values appear for the same logical build across
  `list_builds`/`list_invocations` results.

## Hermeticity Flag Audit

When cache hit rates are poor, verify these flags from invocation data. A
missing flag is not enough to recommend it: confirm the telemetry signal and
the invocation's `data.invocation.buildToolVersion`, then apply the version and
default gates in `bazel-optimization.md`.

| Flag | Purpose | How to Detect a Need |
|------|---------|----------------------|
| `--incompatible_strict_action_env` (Bazel 5–8; default `false`) | Prevents environment variable leakage into actions. Bazel 9 defaults to strict action environments, so add nothing for Bazel 9 alone. An explicit setting in a shared Bazel 5–9 rc file may preserve consistent behavior for older clients. | `ENV_CHANGED` miss reasons; different cache keys for identical code across machines |
| `--nostamp` (Bazel 5–9; stamping defaults to `false`) | Overrides effective stamping. Its absence is already the healthy default; add it only to override an inherited `--stamp` or implement an explicit shared compatibility policy. | Last-wins command-line parsing shows stamping enabled outside an intended release configuration, corroborated by volatile workspace status or `INPUT_CHANGED` misses |
| `--experimental_remote_cache_compression` (Bazel 5–6) or `--remote_cache_compression` (Bazel 7–9); default `false` | Compresses Content Addressable Storage transfers when the remote cache supports compressed blobs | High input fetch and output upload times with moderate blob sizes |
| `--remote_download_minimal` | Only downloads outputs needed locally | `get_invocation.data.profile.bottleneckKind == "output_download_bound"`, or an `output_download_bound` classification from `get_profile_trends`. Do **not** use `metrics.bytesReceived` — it is a whole-host network counter for the machine that ran the build, not Bazel remote-cache traffic |

## Remote Execution Flag Tuning

These flags affect remote execution performance. Recommend values based on observed metrics:

| Flag | What It Controls | How to Tune from Data |
|------|-----------------|----------------------|
| `--jobs=<N>` | Bazel's maximum concurrent actions; it is not remote worker capacity | Use only an explicit numeric value from a complete `get_invocation(includeCommandLine=true)` result, applying last-wins semantics. Compare it only with `get_build_parallelism`'s executing remote-action concurrency. The scheduler executing gauge, unique participating workers, worker slots, and replicas are different quantities and must not be compared with `--jobs`. A peak below `--jobs` is a graph signal only when remote queue wait and scheduler backlog are low. High queueing with low executing parallelism supports worker/scheduler capacity as a hypothesis, and hitting `--jobs` while queueing is high is not a reason to raise it. Treat absent/`auto`/formula/truncated values as an unknown numeric cap. |
| `--remote_timeout=<duration>` (Bazel 5–9) | Maximum wait for remote execution and cache calls, including individual blob transfers; default `60s` | Use remote timing or gRPC evidence to identify the slowest legitimate call and add margin. A `ByteStream.Write` or read can hit this timeout even when no remote action is running. |
| `--remote_retries=<N>` (Bazel 5–9) | Retry count for transient remote failures; default `5` | Do not add `--remote_retries=5`, which only restates the default. Change it only when `get_grpc_health` shows transient errors; deterministic errors make retries waste time. |
| `--remote_default_exec_properties` | Default platform properties for remote actions | Check `get_scheduler_health` per-platform breakdown. Ensure properties match worker platforms that have capacity. |

## Stamping Audit

Stamping is the single most common configuration mistake that kills cache performance. Stamped
actions embed volatile data, such as timestamps or Git SHAs, into outputs and invalidate every
downstream action's cache key.

How to detect stamping problems from Hermetiq data:

1. Look for `workspace_status_command` in invocation command-line arguments.
2. Resolve the effective stamp state from the complete command line using
   last-wins semantics across `--stamp`, `--stamp=true`, `--nostamp`, and
   `--stamp=false`. When no stamp flag is present, Bazel's default is stamping
   disabled; treat that as healthy rather than as a missing recommendation.
3. Only flag stamping when the effective state is enabled outside a configuration
   that intentionally produces release artifacts.
4. Look for `INPUT_CHANGED` misses where the diff shows `inputRootDigest` changed but the
   user made no meaningful source change.
5. Check whether cache miss patterns correlate with time-of-day rather than code changes.

Recommendation: if last-wins parsing finds an inherited `--stamp` and that
configuration should not stamp, add a scoped `--nostamp` override. Do not add it
when no stamp flag is present. An explicit unstamped setting is also reasonable
when the team deliberately documents one compatibility policy across shared rc
files. Keep intentional stamping in a named release configuration, such as
`build:release --stamp`.

## Toolchain Version Management

Different toolchain versions produce different action cache keys. A single developer using a
different compiler version can fragment cache reuse for everyone.

How to detect toolchain drift:

1. `COMMAND_CHANGED` miss reasons where the command diff shows a different compiler path or
   version string.
2. Different `buildToolVersion` values across users.
3. Cache hit rates that drop after toolchain updates and slowly recover.

Recommendation: pin all toolchains via Bazel's toolchain resolution. Prefer hermetic toolchains
downloaded by Bazel over system-installed tools.

**Hermetic toolchains are hermetic in the input tree, not in the libc they need.** A toolchain Bazel
downloads is still a dynamically linked binary, and remote execution runs it against the worker
image's C library. Raising a toolchain pin (a new LLVM, JDK, or Python) can raise the binary's libc
floor above what the worker image supplies, and remote actions then fail with dynamic loader errors
such as `version 'GLIBC_x.y' not found` while local builds on newer hosts keep working. The
toolchain is not "broken" and not out of date — it has outrun the execution environment, and the
worker image is what needs to move. Treat a toolchain bump on a remote-execution project as a
change with a worker image prerequisite. See the `container-image` subsection under bb-runner in
`REFERENCE.md`, and the Remote Execution Environment Mismatch playbook in `SKILL.md`.

## Configuration Recommendations Checklist

When auditing a project's configuration, systematically verify:

- [ ] The invocation's `data.invocation.buildToolVersion` is within the supported Bazel 5–9 range before version-sensitive flags are named
- [ ] Strict action environments are effective (`--incompatible_strict_action_env` for Bazel 5–8; already the Bazel 9 default)
- [ ] Effective last-wins stamping is disabled for non-release builds; no stamp flag is present is already healthy, and an explicit `--nostamp` is recommended only to override inherited configuration or document an intentional shared compatibility policy
- [ ] No volatile `workspace_status_command` values propagate to non-release actions
- [ ] All users and CI share the same `.bazelrc` flags
- [ ] Toolchains are pinned, not system-installed compilers
- [ ] External repositories are pinned to exact versions
- [ ] `--remote_download_minimal` is enabled to reduce network transfer
- [ ] Cache compression uses `--experimental_remote_cache_compression` for Bazel 5–6 or `--remote_cache_compression` for Bazel 7–9 when transfer evidence and server support justify it
- [ ] `--jobs` is set appropriately for the observed worker fleet capacity
- [ ] Platform properties are consistent across the team
