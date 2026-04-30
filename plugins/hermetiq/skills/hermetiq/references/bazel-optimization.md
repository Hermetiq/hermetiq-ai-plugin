# Bazel-Specific Optimization Knowledge

Use this reference when Hermetiq telemetry points to Bazel configuration or build graph changes.
Keep recommendations tied to observed metrics from tools such as GetBuildParallelism,
GetRemoteExecutionAnalytics, GetRemoteActionTrends, GetCacheTrends, and GetTargetTrends.

## Common `.bazelrc` Optimizations

Cache hermeticity flags:

- `build --incompatible_strict_action_env` — Prevents environment variable leakage.
- `build --noexperimental_check_external_repository_files` — Avoids unnecessary re-fetching
  of external repositories.
- `build --experimental_repository_cache_hardlinks` — Reduces disk usage for external
  repositories.

Remote execution tuning:

- `build --remote_timeout=3600` — Prevents timeouts on long-running actions.
- `build --remote_retries=5` — Retries transient failures.
- `build --jobs=<N>` — Controls parallelism. Compare with GetBuildParallelism before changing.
- `build --experimental_remote_cache_compression` — Compresses storage transfers and reduces
  input fetch/output upload time when transfer size is significant.
- `build --remote_download_minimal` — Downloads only outputs needed locally.
- `build --noremote_upload_local_results` — Avoids pushing local execution results to the
  remote cache when local results are not trusted or not useful.

Stamping:

- `build --nostamp` — Disables stamping globally. This is often the highest-impact quick win
  for cache hit rate.
- `build:release --stamp` — Enables stamping only for release builds.

Platform configuration:

- `build --remote_default_exec_properties=OSFamily=Linux` — Keeps default platform matching
  consistent with the worker fleet.
- Use platform mappings to control which actions run remotely versus locally.

## Build Graph Anti-Patterns

When you see these in Hermetiq data, recommend specific fixes:

1. **Mega-target**: A single target with hundreds of source files.
   - Signal: One target appears repeatedly in `expensive_targets` or GetTargetTrends with high
     action count, cost, or duration.
   - Fix: Split into smaller libraries with narrower visibility.

2. **Deep dependency chain**: Long sequential chains of actions.
   - Signal: Low parallelism in GetBuildParallelism despite many total actions, or critical path
     trends dominated by the same target family.
   - Fix: Flatten the dependency graph and use `implementation_deps` to reduce transitive
     dependencies where supported.

3. **Genrule overuse**: Heavy use of `genrule()` for custom logic.
   - Signal: `Genrule` or `GenRule` mnemonic with high miss rate and low CPU efficiency.
   - Fix: Write proper Starlark rules with declared inputs and outputs.

4. **Test macro explosion**: Tests that each rebuild the world.
   - Signal: High `total_executions` for `bazel test` with many repeated actions.
   - Fix: Use shared test libraries and keep test dependencies narrow.

5. **Volatile code generation**: Generators that embed timestamps or non-deterministic output.
   - Signal: High `INPUT_CHANGED` miss rate on actions downstream of a specific generator.
   - Fix: Make code generation deterministic, strip timestamps, and use stable sort orders.

6. **Over-broad dependencies**: Targets depend on aggregate libraries instead of precise inputs.
   - Signal: Frequent rebuilds of unrelated downstream targets after small source changes.
   - Fix: Split shared libraries and remove unused direct dependencies.
