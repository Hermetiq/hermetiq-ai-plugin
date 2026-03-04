# Bazel-Specific Optimization Knowledge

## Common `.bazelrc` Optimizations

**Cache hermeticity flags**:
- `build --incompatible_strict_action_env` — Prevents environment variable leakage
- `build --noexperimental_check_external_repository_files` — Avoids re-fetching external repos
- `build --experimental_repository_cache_hardlinks` — Reduces disk usage for external repos

**Remote execution tuning**:
- `build --remote_timeout=3600` — Prevent timeouts on long-running actions
- `build --remote_retries=5` — Retry transient failures
- `build --jobs=<N>` — Control parallelism (default is 200 for remote; adjust based on data)
- `build --experimental_remote_cache_compression` — Compress storage transfers (reduces I/O time)
- `build --remote_download_minimal` — Only download outputs needed locally (builds without the bytes)
- `build --noremote_upload_local_results` — Do not push local execution results to remote cache

**Stamping (common cache killer)**:
- `build --nostamp` — Disable stamping globally (biggest quick-win for many projects)
- `build:release --stamp` — Only enable stamping for release builds

**Platform configuration**:
- `build --remote_default_exec_properties=OSFamily=Linux` — Ensure consistent platform matching
- Use platform mappings to control which actions run remotely versus locally

## Build Graph Anti-Patterns

When you see these in Hermetiq data, recommend specific fixes:

1. **Mega-target**: A single target with hundreds of source files.
   - **Signal**: One target appears repeatedly in `expensive_targets` with high action count
   - **Fix**: Split into smaller libraries with narrower visibility

2. **Deep dependency chain**: Long sequential chains of actions.
   - **Signal**: Low parallelism in GetBuildParallelism despite many total actions
   - **Fix**: Flatten dependency graph; use `implementation_deps` to reduce transitives

3. **Genrule overuse**: Heavy use of `genrule()` for custom logic.
   - **Signal**: `Genrule` mnemonic with high miss rate and low CPU efficiency
   - **Fix**: Write proper Starlark rules with declared inputs/outputs

4. **Test macro explosion**: Tests that each rebuild the world.
   - **Signal**: High `total_executions` for `bazel test` with many repeated actions
   - **Fix**: Use shared test libraries; ensure test dependencies are narrow

5. **Volatile code generation**: Generators that embed timestamps or non-deterministic output.
   - **Signal**: High `INPUT_CHANGED` miss rate on actions downstream of a specific genrule
   - **Fix**: Make codegen deterministic; strip timestamps; use stable sort orders
