# Hermetiq AI Plugin

Give your AI agent deep Bazel expertise — backed by real build data from [Hermetiq](https://hermetiq.com).

This plugin adds a skill and MCP server that let Claude Code, Claude Desktop, or Codex analyze build performance, fix cache misses, optimize remote execution, and debug Buildbarn infrastructure using your project's actual metrics.

## Capabilities

- **Diagnose slow builds** — find critical path bottlenecks, regressions, and parallelism gaps
- **Fix cache misses** — pinpoint miss reasons and recommend targeted fixes
- **Optimize remote execution** — reduce queue wait, right-size workers, cut RBE costs
- **Debug infrastructure** — investigate Buildbarn storage, scheduler, and worker fleet health
- **Audit configuration** — review `.bazelrc` flags, hermeticity, and build graph patterns
- **Track trends** — compare performance across time periods, branches, and teams

## Prerequisites

A [Hermetiq](https://dashboard.hermetiq.io) account with at least one project receiving BEP events.

## Install in Claude Code

```bash
# Add the Hermetiq marketplace
/plugin marketplace add Hermetiq/hermetiq-ai-plugin

# Install the plugin
/plugin install hermetiq@hermetiq
```

> The plugin marketplace is a Claude Code (CLI) feature, not Claude Desktop.

The plugin configures the MCP server automatically. On first use you'll authenticate via your Hermetiq account. Log in to [dashboard.hermetiq.io](https://dashboard.hermetiq.io) beforehand for a seamless experience.

Authentication uses OAuth2 Dynamic Client Registration via [Stytch](https://stytch.com/docs/connected-apps/guides/remote-mcp-servers). If you hit auth errors, re-authenticate with `/mcp` and follow the prompts.

### Self-hosted / on-prem

The plugin defaults to Hermetiq Cloud (`https://mcp.cloud-usc1.hermetiq.io`). If you run Hermetiq in your own infrastructure, set `HERMETIQ_MCP_URL` to your deployment's MCP endpoint before launching Claude Code:

```bash
export HERMETIQ_MCP_URL=https://mcp.hermetiq.your-domain.example
```

The plugin picks this up automatically; no edits to `plugin.json` are needed.

### Manual MCP server setup

To configure the MCP server without the plugin, add this to your Claude Code MCP settings (swap the URL for your on-prem endpoint if applicable):

```json
{
  "mcpServers": {
    "hermetiq": {
      "type": "http",
      "url": "https://mcp.cloud-usc1.hermetiq.io"
    }
  }
}
```

## Usage

Claude activates the skill automatically when you ask about build performance. You can also invoke it directly:

```
/hermetiq analyze my latest build
/hermetiq why is my cache hit rate dropping?
/hermetiq compare this week's builds to last week
```

Or ask naturally:

```
Why did my build take 20 minutes today?
Show me cache miss trends for the last 7 days
Which targets are most expensive to execute remotely?
```

### Canonical MCP workflow examples

The plugin follows the official Hermetiq MCP catalog returned by `tools/list`.
Tool names are lower snake case; generated protobuf names and old PascalCase
aliases are not supported.

| User request | Expected canonical sequence |
|---|---|
| "Which Hermetiq project should we inspect?" | `list_my_projects` |
| "This opaque build URL is slow" | `resolve_build_or_invocation` → `get_build_details` → `get_invocation_insights` |
| "Analyze this known invocation" | `analyze_invocation` prompt: `get_invocation(includeCommandLine=true)` → `get_invocation_insights` → `summarize_cache_events` when available; when remote execution is enabled, check `get_project.data.completedActionLogEnabled`, use `analyze_remote_execution` → `get_build_parallelism(bucketSeconds=5)` only when action logging is on, compare only executing remote-action concurrency with a complete last-wins numeric `--jobs`, treat the padded/shared `get_scheduler_health` window as corroboration rather than worker slots or replicas, require `get_worker_scaling_timeline`'s time-aligned desired/available/ready series when listed before claiming autoscaler delay, and follow `available_separately` with same-window `list_buildbarn_events` without inferring causality from timestamp alignment |
| "Why did cache misses increase in this invocation?" | `group_cache_events` with `hit="miss"` → `find_cache_events` only when groups exist |
| "Why did these actions fail?" | `find_actions` with `result="failed"` → `get_action_execution` for returned action IDs |
| "Is Buildbarn healthy?" | `summarize_infrastructure_health` with `timeRange="1h"`, then a component tool only when the summary identifies an anomaly |
| "Audit Buildbarn storage configuration" | `analyze_buildbarn_storage` without a store filter → `get_buildbarn_config` for discovered files; identify CAS/AC/ISCC/FSAC from configuration content before applying a store focus, then use `get_storage_health` only as corroborating runtime telemetry |

Project scope comes from the server-resolved default or the user's sticky
`select_project` preference; analytics tools do not accept a model-supplied
project override. The skill uses the current project without prompting and
switches only when the user explicitly requests it. Optional capabilities are
absent from `tools/list` when unavailable, and the skill will say so instead of
substituting unrelated evidence.

ConfigSet changes require a separate host-visible confirmation immediately
before `import_config_map_yaml`, `save_config_set`, or
`create_config_set_pull_request`. The skill never infers confirmation or retries
an ambiguous mutation blindly.

## Install in Claude Desktop

### 1. Add the MCP server

Go to **Settings > Connectors** and add:

```
https://mcp.cloud-usc1.hermetiq.io
```

> Self-hosted? Use your on-prem MCP endpoint instead (e.g. `https://mcp.hermetiq.your-domain.example`).

### 2. Package and upload the skills

```bash
git clone https://github.com/Hermetiq/hermetiq-ai-plugin
cd hermetiq-ai-plugin/plugins/hermetiq/skills
zip -r hermetiq.zip hermetiq/
zip -r on-prem-gke-install.zip on-prem-gke-install/
```

> Each zip must preserve its folder structure — for example,
> `hermetiq.zip` contains `hermetiq/SKILL.md`, not a bare `SKILL.md` at the
> root. Upload both archives to install the supported build-analysis and
> on-premises GKE installation skills.

Then in Claude Desktop:

1. Go to **Customize > Skills**
2. Click **+** > **Upload a skill**
3. Select `hermetiq.zip`, then repeat for `on-prem-gke-install.zip`

### 3. Enable code execution

Go to **Settings > Capabilities** and toggle on **Code execution and file creation**.

> Skills require a **Pro**, **Max**, **Team**, or **Enterprise** plan.

## Install in Codex

### 1. Add the MCP server

```bash
codex mcp add hermetiq --url https://mcp.cloud-usc1.hermetiq.io
```

> Self-hosted? Replace the URL with your on-prem MCP endpoint (e.g. `https://mcp.hermetiq.your-domain.example`).

Verify with `codex mcp list` or `codex mcp get hermetiq`.

### 2. Authenticate

In Codex Desktop, click the **Authenticate** button. Or from the CLI:

```bash
codex mcp login hermetiq
```

> Log in to [dashboard.hermetiq.io](https://dashboard.hermetiq.io) first for a smoother flow. See [Codex MCP docs](https://developers.openai.com/codex/mcp) for details.

### 3. Install the skill

```bash
git clone https://github.com/Hermetiq/hermetiq-ai-plugin
cd hermetiq-ai-plugin
mkdir -p ~/.codex/skills
cp -R plugins/hermetiq/skills/hermetiq ~/.codex/skills/
cp -R plugins/hermetiq/skills/on-prem-gke-install ~/.codex/skills/
```

### 4. Restart Codex

Restart Codex to pick up the new MCP server and skill.

Then ask build-performance questions naturally or invoke the skill by name:

```
Use the hermetiq skill to analyze my latest build
Why is remote execution queue time high this week?
Show cache miss reasons by mnemonic for my failing builds
```

## What's included

| File | Description |
|------|-------------|
| `SKILL.md` | Core skill with MCP-aware tool selection, playbooks, and recommendation rules |
| `references/REFERENCE.md` | Hermetiq data model, MCP tool constraints, analytics outputs, and Buildbarn architecture |
| `references/build-configuration.md` | Configuration drift, hermeticity, stamping, toolchain, and flag audit guidance |
| `references/bazel-optimization.md` | Common Bazel flags and build graph anti-patterns |
| `references/infrastructure-tuning.md` | Buildbarn storage, worker, scheduler, and scaling guidance |
| `evals/evals.json` | Skill behavior suite covering canonical selection, response-contract semantics, errors, disabled capabilities, and mutation safety |
| `evals/canonical-mcp-catalog.json` | Release snapshot of canonical tools plus explicit prompt/resource/external-tool allowlists |
| `on-prem-gke-install/SKILL.md` | GKE installation workflow for self-hosted Hermetiq and Buildbarn |
| `on-prem-gke-install/references/known-gotchas.md` | Verified GKE, Gateway API, Auth0, Helm, and Buildbarn installation pitfalls |
| `scripts/validate-mcp-catalog.py` | Mechanical catalog-to-skill drift validator; pass `--server-catalog` to compare with the cloud-native fixture |

## Release versioning

The GitHub release tag and the Claude marketplace plugin version identify
different things:

- A GitHub tag such as `v0.9.6-beta` identifies a repository snapshot and its
  downloadable manual-install archives.
- The SemVer in `plugins/hermetiq/.claude-plugin/plugin.json` and both version
  fields in `.claude-plugin/marketplace.json` is Claude Code's update signal.

Every release that changes `plugins/hermetiq/` must increase the plugin SemVer
in all three fields before the GitHub tag is created. A new GitHub tag must not
reuse a plugin version from an earlier tag. Pull requests enforce this rule with
`scripts/check-plugin-version.py`; release reviewers should record both versions
in release notes.

## Developer validation

Validate the skill, references, README, and eval sequences against the checked-in
catalog and the authoritative server fixture:

```bash
python3 scripts/validate-mcp-catalog.py \
  --server-catalog ../cloud-native/bep-nats/mcpv2/testdata/catalog/current.json
python3 scripts/check-plugin-version.py --base-ref origin/main
python3 -m unittest scripts/test_validate_mcp_catalog.py scripts/test_run_mcp_evals.py -v
```

Run the real Claude/official-MCP canary suite with the API key and fixture IDs in
the environment. In addition to tool selection, the suite requires supported
response claims and rejects forbidden legacy fields or over-specific diagnoses.
The runner writes one raw/scored JSON artifact per case plus an aggregate
`run.json`; it never writes the API key:

```bash
ANTHROPIC_API_KEY=... \
BUILD_ID=... INVOCATION_ID=... FAILURE_INVOCATION_ID=... \
REMOTE_EXEC_INVOCATION_ID=... LOCAL_INVOCATION_ID=... \
CONFIG_SET_NAME=... REQUEST_ID=... \
python3 scripts/run-mcp-evals.py \
  --server-catalog ../cloud-native/bep-nats/mcpv2/testdata/catalog/current.json \
  --output /tmp/hermetiq-skill-eval
```
