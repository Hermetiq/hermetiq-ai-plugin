# Bazel-Specific Optimization Knowledge

Use this reference when Hermetiq telemetry points to Bazel configuration or build graph changes.
Keep recommendations tied to observed metrics from tools such as get_build_parallelism,
analyze_remote_execution, get_remote_action_trends, get_cache_trends, and get_target_trends.

## Common `.bazelrc` Optimizations

This reference supports Bazel 5.x through 9.x. Before naming a flag, read
`data.invocation.buildToolVersion` from
`get_invocation(includeCommandLine=true)`, parse its major version, and use only
the matching row below. If the field is absent, unparseable, older than 5, or
newer than 9, do not emit a version-sensitive `.bazelrc` line. Ask for the Bazel
version or have the user confirm the candidate with `bazel help build --long`.

Do not recommend a flag merely because it appears in this table. Require the
listed telemetry signal, skip flags already effective in the invocation, and
explain the expected tradeoff.

| Flag | Supported Bazel majors | Default in supported versions | Recommendation gate |
|------|------------------------|-------------------------------|---------------------|
| `--incompatible_strict_action_env` | 5–9 | `false` in 5–8; `true` in 9 | Add only when environment drift is evidenced. Bazel 9 defaults to strict action environments, so do not add the flag for Bazel 9 alone; an explicit setting in a shared Bazel 5–9 rc file can document and preserve the same behavior for older clients. |
| `--experimental_repository_cache_hardlinks` | 5–9 | `false` | Consider only for measured external-repository disk or copy overhead. Bazel help says this hardlinks cache hits instead of copying them; ensure repository outputs are not mutated in place. |
| `--remote_timeout=<duration>` | 5–9 | `60s` | Raise only when a remote execution or cache/blob-transfer call can legitimately exceed 60 seconds. Size from the slowest expected call plus margin; this is not an action-only timeout. |
| `--remote_retries=<N>` | 5–9 | `5` | Do not add `--remote_retries=5`; it restates the default. Change the value only for evidenced transient failures and explain the added retry latency. |
| `--jobs=<N>` | 5–9 | `auto` | Set explicitly only after the complete command line and remote concurrency/queue evidence show the client cap is binding. |
| `--experimental_remote_cache_compression` | 5–6 | `false` | Enable only when cache transfer time is significant and the remote cache supports compressed blobs. |
| `--remote_cache_compression` | 7–9 | `false` | Same gate as above; this is the current spelling. Do not emit the experimental predecessor for these versions. |
| `--remote_download_minimal` | 5–9 | output mode is version/configuration dependent | Use only for output-download-bound builds whose local consumers do not require all outputs. |
| `--noremote_upload_local_results` | 5–9 | local-result upload is `true` | Disable only when local results are not trusted or useful to the shared cache. |
| `--nostamp` / `--stamp` | 5–9 | stamping is `false` | Do not add `--nostamp` just to restate the default. Use it to override an inherited `--stamp` or to make a shared release-only stamping policy explicit; put `--stamp` only in the release config. |
| `--remote_default_exec_properties=<key=value>` | 5–9 | unset | Add only when observed platform properties do not match an available worker pool. |

For Bazel 5–6, copy only this version-selected compression setting after the
compression gate is satisfied:

```bazelrc
build --experimental_remote_cache_compression
```

For Bazel 7–9, copy only the canonical setting instead:

```bazelrc
build --remote_cache_compression
```

Version-neutral examples after their telemetry gates are satisfied:

```bazelrc
# Bazel 5-9; value must come from measured remote-call duration
build --remote_timeout=1800s

# Bazel 5-9; match properties actually advertised by the worker fleet
build --remote_default_exec_properties=OSFamily=Linux
```

Do not add `--nostamp` merely because it is absent: absence means Bazel's
default unstamped behavior is effective. Only when last-wins parsing finds an
inherited `--stamp` for a configuration that should be unstamped should a
specific override be suggested, for example:

```bazelrc
build:ci --nostamp
build:release --stamp
```

Use platform mappings to control which actions run remotely versus locally.

## Build Graph Anti-Patterns

When you see these in Hermetiq data, recommend specific fixes:

1. **Mega-target**: A single target with hundreds of source files.
   - Signal: One target appears repeatedly in `data.expensiveTargets` or `get_target_trends` with high
     action count, cost, or duration.
   - Fix: Split into smaller libraries with narrower visibility.

2. **Deep dependency chain**: Long sequential chains of actions.
   - Signal: Low parallelism in get_build_parallelism despite many total actions, or critical path
     trends dominated by the same target family. get_build_parallelism counts only
     remote-executed actions and begins at the first remote action, so an empty series means no
     remote execution was observed rather than a serial graph. A short nonempty series proves
     remote actions ran but does not by itself diagnose the graph — confirm
     `data.invocation.remoteExecutionEnabled` and `get_project.data.completedActionLogEnabled`
     before reading it as a parallelism signal.
   - Fix: Flatten the dependency graph and use `implementation_deps` to reduce transitive
     dependencies where supported.

3. **Genrule overuse**: Heavy use of `genrule()` for custom logic.
   - Signal: `Genrule` or `GenRule` mnemonic with high miss rate and low CPU efficiency.
   - Fix: Write proper Starlark rules with declared inputs and outputs.

4. **Test macro explosion**: Tests that each rebuild the world.
   - Signal: High `totalExecutions` for `bazel test` with many repeated actions.
   - Fix: Use shared test libraries and keep test dependencies narrow.

5. **Volatile code generation**: Generators that embed timestamps or non-deterministic output.
   - Signal: High `INPUT_CHANGED` miss rate on actions downstream of a specific generator.
   - Fix: Make code generation deterministic, strip timestamps, and use stable sort orders.

6. **Over-broad dependencies**: Targets depend on aggregate libraries instead of precise inputs.
   - Signal: Frequent rebuilds of unrelated downstream targets after small source changes.
   - Fix: Split shared libraries and remove unused direct dependencies.
