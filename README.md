# Hermetiq AI Plugin

Give your AI agent Bazel expertise backed by real build data from [Hermetiq](https://hermetiq.com).

The Claude Code plugin bundles a connection to the Hermetiq MCP server and two skills:

- **[`hermetiq`](plugins/hermetiq/skills/hermetiq/SKILL.md)** analyzes build performance, cache misses, failures, and Buildbarn infrastructure using your project's telemetry.
- **[`on-prem-gke-install`](plugins/hermetiq/skills/on-prem-gke-install/SKILL.md)** guides Hermetiq and Buildbarn installation on GKE, including Helm chart testing, Auth0 setup, and installation troubleshooting.

Claude Desktop chat and Codex can use the same skills through the manual setup below.

[Claude Code](#install-in-claude-code) · [Claude Desktop chat](#install-in-claude-desktop-chat) · [Codex](#manual-setup-in-codex) · [Upgrading](#upgrade-to-the-latest-version) · [Usage](#usage) · [Developer validation](#developer-validation)

## Capabilities

- **Diagnose slow builds** — find critical-path bottlenecks, regressions, and parallelism gaps
- **Investigate cache misses** — explain recorded miss reasons and recommend targeted fixes
- **Diagnose failures** — investigate failed or flaky tests and remote execution environment errors
- **Improve remote execution** — recommend queue, worker-sizing, and cost improvements from available evidence
- **Debug infrastructure** — investigate Buildbarn storage, scheduler, and worker fleet health
- **Audit configuration** — review `.bazelrc` flags, hermeticity, and build graph patterns
- **Track trends** — compare builds across time periods, repositories, and branches

## Prerequisites

### Build analysis

Access to a Hermetiq Cloud or self-hosted project receiving Bazel Build Event
Protocol (BEP) events. For Cloud, sign in at
[dashboard.hermetiq.io](https://dashboard.hermetiq.io); for self-hosted deployments,
use your deployment's dashboard and MCP endpoint.

Some investigations need additional data: cache-miss details require cache-event
telemetry, profile analysis requires captured Bazel profiles, and remote-action
details and parallelism require completed action logging. Infrastructure health
needs metrics; live configuration inspection needs Kubernetes access from the
server. Cost analysis is available only on deployments exposing the Cloud/OpenCost
capability. The skill reports unavailable tools or missing telemetry explicitly.

### GKE installation

The installation skill needs access to the [Hermetiq Helm chart repository](https://github.com/Hermetiq/hermetiq-k8s),
Git, Helm, and authenticated `kubectl`/Google Cloud tooling with the permissions
needed for your target cluster. Prepare deployment-specific namespace, domain/DNS,
database, and Auth0 settings using that repository's installation guide. A new
installation does not need an existing project with build telemetry. See the
[installation skill](plugins/hermetiq/skills/on-prem-gke-install/SKILL.md) for
released-chart and unreleased-PR workflows.

## Install in Claude Code

Already installed? See [Upgrade to the latest version](#upgrade-to-the-latest-version).

Run these slash commands one at a time in a Claude Code terminal session. When
the plugin details open, choose the installation scope and complete the install:

```text
/plugin marketplace add Hermetiq/hermetiq-ai-plugin
/plugin install hermetiq@hermetiq
/reload-plugins
```

Claude Code plugins also work in the desktop app's **Code** tab; use its plugin
browser as described in the [Claude Code plugin documentation](https://code.claude.com/docs/en/discover-plugins).
For Desktop **chat**, follow the [manual setup](#install-in-claude-desktop-chat).

The plugin configures the MCP connection automatically. On first use, authenticate
with your Hermetiq account. Hermetiq Cloud uses OAuth 2.0 Dynamic Client
Registration through Stytch; signing in to
[the Cloud dashboard](https://dashboard.hermetiq.io) beforehand can simplify login.
If authentication fails, open `/mcp`, select the Hermetiq server, and follow the
sign-in prompts.

### Self-hosted / on-prem

The plugin defaults to Hermetiq Cloud (`https://mcp.cloud-usc1.hermetiq.io`). For a
self-hosted deployment, set `HERMETIQ_MCP_URL` in the environment that launches
Claude Code:

```bash
export HERMETIQ_MCP_URL=https://mcp.hermetiq.your-domain.example/
```

Copy your deployment's **exact** MCP resource URL, including its path and any
trailing slash. In the Auth0 setup covered by the installation skill, it must
match the API identifier/audience, `api.mcpResourceUrl`, and protected-resource
metadata byte for byte. See the [on-prem authentication guidance](plugins/hermetiq/skills/on-prem-gke-install/SKILL.md#5-auth0--oidc-setup).
The plugin reads the environment variable automatically; no manifest edit is needed.

### MCP-only setup

To configure MCP access without the bundled skills, run this in your terminal:

```bash
claude mcp add --transport http --scope user hermetiq https://mcp.cloud-usc1.hermetiq.io
```

For self-hosted deployments, substitute the exact URL described above. Authenticate
through `/mcp` in Claude Code. See [Claude Code's MCP setup documentation](https://code.claude.com/docs/en/mcp)
for other configuration scopes.

## Install in Claude Desktop chat

This installs the skills and MCP connector separately for chat.

### 1. Enable code execution

Go to **Settings > Capabilities** and enable **Code execution and file creation**.
Skills are available on Free, Pro, Max, Team, and Enterprise plans; organization
policies can restrict them. See [Claude's skill setup instructions](https://support.claude.com/en/articles/12512180-use-skills-in-claude).

### 2. Add the MCP server

Go to **Settings > Connectors**, add a custom connector with this URL, and complete
sign-in:

```text
https://mcp.cloud-usc1.hermetiq.io
```

For self-hosted deployments, use the exact configured MCP resource URL, including
any trailing slash; see [Self-hosted / on-prem](#self-hosted--on-prem).

### 3. Package and upload the skills

For a new checkout:

```bash
git clone https://github.com/Hermetiq/hermetiq-ai-plugin
cd hermetiq-ai-plugin/plugins/hermetiq/skills
zip -r -FS hermetiq.zip hermetiq/
zip -r -FS on-prem-gke-install.zip on-prem-gke-install/
```

Each ZIP must contain its skill folder: for example, `hermetiq.zip` contains
`hermetiq/SKILL.md`. The `-FS` option also removes obsolete archive entries when
you rebuild a ZIP from the same directory during an upgrade.

In Claude Desktop:

1. Go to **Customize > Skills**.
2. Click **+** > **Create skill** > **Upload a skill**.
3. Upload `hermetiq.zip` and enable it. Upload and enable
   `on-prem-gke-install.zip` as well if you want GKE installation guidance.

Ask to use the skills by name, for example, "Use the hermetiq skill to analyze my
latest build." The `/hermetiq:hermetiq` namespace applies to the Claude Code
marketplace plugin.

## Manual setup in Codex

These steps add an MCP connection and standalone skills to Codex.

### 1. Add the MCP server

```bash
codex mcp add hermetiq --url https://mcp.cloud-usc1.hermetiq.io
```

For self-hosted deployments, use the exact configured MCP resource URL, including
any trailing slash; see [Self-hosted / on-prem](#self-hosted--on-prem).
Verify the connection configuration with `codex mcp list` or `codex mcp get hermetiq`.

### 2. Authenticate

In the desktop app, open **Settings > MCP servers**, find **hermetiq**, and select
**Authenticate**. Or use the CLI:

```bash
codex mcp login hermetiq
```

For Cloud, signing in to [the dashboard](https://dashboard.hermetiq.io) first can
simplify login. See the [Codex MCP documentation](https://developers.openai.com/codex/mcp).

### 3. Install the skills

For a new checkout and installation:

```bash
git clone https://github.com/Hermetiq/hermetiq-ai-plugin
cd hermetiq-ai-plugin
mkdir -p ~/.agents/skills
cp -R plugins/hermetiq/skills/hermetiq ~/.agents/skills/
cp -R plugins/hermetiq/skills/on-prem-gke-install ~/.agents/skills/
```

`~/.agents/skills` is the current documented user skill location. Earlier versions
of this README used `~/.codex/skills`; if you already installed there, follow the
[upgrade instructions](#upgrade-to-the-latest-version) for your existing location
instead of creating duplicate copies. See [Codex skill locations](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).

### 4. Start a new Codex session

Restart Codex to load the MCP configuration. Subsequent skill-file changes are
detected automatically; restart if an updated skill does not appear.

Ask naturally or name the skill:

```text
Use the hermetiq skill to analyze my latest build
Why is remote execution queue time high this week?
Use the on-prem-gke-install skill to plan a GKE test installation
```

## Upgrade to the latest version

### Claude Code

Run these commands in your terminal to refresh the marketplace and update the
installed plugin:

```bash
claude plugin marketplace update hermetiq
claude plugin update hermetiq@hermetiq
```

For a project or local installation, run from that project and add
`--scope project` or `--scope local` to the second command, matching the scope
shown by `claude plugin list`.

Restart Claude Code, or run `/reload-plugins` inside your open session, to load
the update. Check the installed version with `claude plugin list`.

Third-party marketplaces have automatic updates off by default. To enable them,
open `/plugin` → **Marketplaces** → **hermetiq** → **Enable auto-update**.
See [Claude Code's plugin update documentation](https://code.claude.com/docs/en/discover-plugins#keep-plugins-updated).
Updates follow the marketplace's configured branch or tag; the installation
above follows `main`, while a marketplace pinned to a release tag stays on that tag.

### Claude Desktop and Codex manual installs

The uploaded or copied skills must be refreshed separately. From the root of
your existing repository clone, on the `main` branch, fetch the latest changes:

```bash
git pull --ff-only origin main
```

**Claude Desktop:** Rebuild the ZIP files with the
[packaging commands](#3-package-and-upload-the-skills), running them from
`plugins/hermetiq/skills/`. Replace the previous uploads in **Customize > Skills**
and enable the updated skills.

**Codex:** From the repository root, replace the installed skill contents:

```bash
rsync -a --delete plugins/hermetiq/skills/hermetiq/ ~/.agents/skills/hermetiq/
rsync -a --delete plugins/hermetiq/skills/on-prem-gke-install/ ~/.agents/skills/on-prem-gke-install/
```

If your existing installation uses `~/.codex/skills`, substitute that destination
in both commands. These commands overwrite local edits and remove files no longer
shipped in those two skill folders; keep customizations elsewhere before updating.
Restart Codex if the updated skills do not appear.

## Usage

The agent can select the relevant skill for build performance, build/test
failures, infrastructure questions, or GKE installation. To select a skill
explicitly in a Claude Code marketplace installation, use its plugin namespace:

```text
/hermetiq:hermetiq analyze my latest build
/hermetiq:hermetiq why did my remote actions fail with GLIBC errors?
/hermetiq:hermetiq compare this week's builds to last week
/hermetiq:on-prem-gke-install help me install Hermetiq in a new GKE test namespace
```

Or ask naturally:

```text
Why did my build take 20 minutes today?
Show me cache miss trends for the last 7 days
Which tests have been flaky this week?
Help me validate the Helm values for a self-hosted Hermetiq deployment
```

### Canonical MCP workflow examples

The build-analysis skill uses canonical tools from the connected server's
`tools/list`. When the client supports MCP prompt retrieval, it can load a matching
server prompt; retrieving a prompt supplies instructions, not investigation
results. Otherwise, the agent follows the skill's playbooks directly.

These are starting points, not complete call sequences. The linked playbooks
cover capability checks, conditional branches, and the evidence needed for a
conclusion.

| User request | Typical starting calls | Prompt / playbook |
|---|---|---|
| "Which Hermetiq projects can I inspect?" | `list_my_projects`; selection changes only on an explicit request | [Project context](plugins/hermetiq/skills/hermetiq/SKILL.md#project-build-and-invocation-context) |
| "This build URL is slow" | Extract the opaque ID → `resolve_build_or_invocation`; for a build, `get_build_details` → `get_invocation_insights` for a returned invocation | [Slow build or invocation](plugins/hermetiq/skills/hermetiq/SKILL.md#slow-build-or-invocation) |
| "Analyze this known invocation" | `get_invocation(includeCommandLine=true)` → `get_invocation_insights`; diagnose failures before performance advice, then follow the cache and remote-capacity branches | `analyze_invocation` / [playbook](plugins/hermetiq/skills/hermetiq/SKILL.md#slow-build-or-invocation) |
| "Why did this invocation miss the cache?" | `group_cache_events(hit="miss")` and `summarize_cache_events`; inspect matching events with `find_cache_events(hit="miss")` only when groups exist | `debug_cache_misses` / [cache guidance](plugins/hermetiq/skills/hermetiq/SKILL.md#cache-effectiveness) |
| "Why did this invocation fail?" | `get_invocation` → `find_actions(result="failed")`; inspect status, aggregates, and successful-retry evidence before fetching needed `get_action_execution` details | `investigate_failure` / [playbook](plugins/hermetiq/skills/hermetiq/SKILL.md#failure-or-test-failure) |
| "How was Buildbarn health over the last hour?" | `summarize_infrastructure_health(timeRange="1h")`; inspect components whose assessment is not `healthy`, using the same window, and report missing telemetry | `infra_health` / [infrastructure guidance](plugins/hermetiq/skills/hermetiq/SKILL.md#buildbarn-infrastructure) |
| "Audit Buildbarn storage configuration" | `analyze_buildbarn_storage` without a store filter → `get_buildbarn_config` using the bare configuration filename; identify stores from content, then check available geometry, topology, and runtime health | `analyze_storage_config` / [playbook](plugins/hermetiq/skills/hermetiq/SKILL.md#storage-configuration-audit) |

For opaque IDs, branch on the resolver's `kind`: use the invocation flow for
`invocation` and stop on `not_found`. For `build`, pass its returned ID and
partition bounds unchanged to the detail call. Cache investigations must confirm
coverage before interpreting empty groups as no misses, and compare like-for-like
history before claiming an increase. Failure investigations use build logs and
test results when action rows do not explain the failure. Empty storage findings
do not establish healthy configuration.

Project scope comes from the server-resolved default or the user's saved
`select_project` preference. Analytics tools do not accept a project override;
the skill uses the current project and switches only when explicitly requested.
Read structured results from `data` and check `truncated`/`truncatedFields` before
claiming completeness. A listed tool can still report missing telemetry; missing
or incomplete evidence is not a zero measurement or a healthy verdict.

For remote-capacity analysis, completed action logging gates remote-action
details and parallelism. Available scheduler telemetry can still be inspected
when that logging is off. See the [parallelism guidance](plugins/hermetiq/skills/hermetiq/SKILL.md#parallelism-and-critical-path)
for client `--jobs` limits, worker capacity, and scale-up evidence.

ConfigSet changes require authorization for the reviewed project, files, version,
and side effects, including the confirmation required by the connected tool.
The skill preserves authorization that covers that exact action and does not
blindly retry an ambiguous mutation.

## What's included

Build-analysis skill files, relative to [`plugins/hermetiq/skills/hermetiq/`](plugins/hermetiq/skills/hermetiq/):

| File | Description |
|---|---|
| [`SKILL.md`](plugins/hermetiq/skills/hermetiq/SKILL.md) | Tool selection, playbooks, and evidence rules |
| [`references/REFERENCE.md`](plugins/hermetiq/skills/hermetiq/references/REFERENCE.md) | Data model, MCP contracts, and Buildbarn architecture |
| [`references/build-configuration.md`](plugins/hermetiq/skills/hermetiq/references/build-configuration.md) | Configuration drift, hermeticity, stamping, toolchains, and flag audits |
| [`references/bazel-optimization.md`](plugins/hermetiq/skills/hermetiq/references/bazel-optimization.md) | Bazel flags and build graph patterns |
| [`references/infrastructure-tuning.md`](plugins/hermetiq/skills/hermetiq/references/infrastructure-tuning.md) | Storage, worker, scheduler, and scaling guidance |
| [`evals/evals.json`](plugins/hermetiq/skills/hermetiq/evals/evals.json) | Behavior cases for tool selection, response contracts, availability, and mutations |
| [`evals/canonical-mcp-catalog.json`](plugins/hermetiq/skills/hermetiq/evals/canonical-mcp-catalog.json) | Tool snapshot and prompt/resource allowlists |

GKE installation skill files, relative to [`plugins/hermetiq/skills/on-prem-gke-install/`](plugins/hermetiq/skills/on-prem-gke-install/):

| File | Description |
|---|---|
| [`SKILL.md`](plugins/hermetiq/skills/on-prem-gke-install/SKILL.md) | GKE installation and troubleshooting workflow |
| [`references/known-gotchas.md`](plugins/hermetiq/skills/on-prem-gke-install/references/known-gotchas.md) | GKE, Gateway API, Auth0, Helm, and Buildbarn installation pitfalls |

Repository tooling, relative to the repository root:

| File | Description |
|---|---|
| [`scripts/testdata/cloud-native-mcp-catalog.json.gz`](scripts/testdata/cloud-native-mcp-catalog.json.gz) | Compressed server fixture for deterministic validation |
| [`scripts/testdata/cloud-native-mcp-catalog.provenance.json`](scripts/testdata/cloud-native-mcp-catalog.provenance.json) | Fixture source revision and checksum |
| [`scripts/validate-mcp-catalog.py`](scripts/validate-mcp-catalog.py) | Catalog-to-skill drift validator |
| [`scripts/sync-mcp-catalog.py`](scripts/sync-mcp-catalog.py) | Refresh both catalog snapshots from the server fixture |
| [`scripts/build-release-zip.sh`](scripts/build-release-zip.sh) | Build skill-only release archives, excluding development evals |

## Release versioning

The GitHub release tag and Claude marketplace plugin version identify different things:

- A GitHub tag such as `v0.9.6-beta` identifies a repository snapshot and its
  downloadable manual-install archives.
- The SemVer in `plugins/hermetiq/.claude-plugin/plugin.json` and both version
  fields in `.claude-plugin/marketplace.json` is Claude Code's update signal.

Changes under `plugins/hermetiq/` must increase the plugin SemVer in all three
fields before release. Pull requests check synchronization and require an increase
relative to the PR base with `scripts/check-plugin-version.py`.

Release reviewers must also check that a new GitHub tag does not reuse an earlier
tag's plugin version and record both versions in the release notes. The version
checker compares against a Git base ref; it does not inspect release tags.

## Developer validation

From the repository root, use Python 3.12 (matching CI) and the bundled server
fixture. These checks do not need access to the private server repository:

```bash
hermetiq_catalog="$(mktemp)"
gzip -dc scripts/testdata/cloud-native-mcp-catalog.json.gz > "$hermetiq_catalog"
python3 scripts/validate-mcp-catalog.py \
  --server-catalog "$hermetiq_catalog" \
  --server-provenance scripts/testdata/cloud-native-mcp-catalog.provenance.json
python3 scripts/check-plugin-version.py
python3 scripts/validate-bazel-guidance.py
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

For a plugin-changing PR, also run `python3 scripts/check-plugin-version.py --base-ref origin/main`
against an up-to-date base ref. Match CI's manifest checks with:

```bash
npx --yes @anthropic-ai/claude-code@2.1.231 plugin validate --strict .claude-plugin/marketplace.json
npx --yes @anthropic-ai/claude-code@2.1.231 plugin validate --strict plugins/hermetiq
```

### Refresh the server fixture (maintainers)

CI validates every distributable text file under `plugins/hermetiq/skills/**`
and eval arguments against an exact compressed snapshot of
`Hermetiq/cloud-native`'s private
`bep-nats/mcpv2/testdata/catalog/current.json`. The compact plugin catalog's
`source`, `sourceRevision`, `server`, and `serverVersion` fields record the
provenance. Because this public repository's GitHub token cannot read the
private source repository, refresh and verify both snapshots locally from the
latest `cloud-native` `origin/main` before releasing:

```bash
git -C ../cloud-native fetch origin main
git -C ../cloud-native show \
  origin/main:bep-nats/mcpv2/testdata/catalog/current.json \
  > /tmp/hermetiq-mcp-catalog.json
python3 scripts/sync-mcp-catalog.py \
  --server-catalog /tmp/hermetiq-mcp-catalog.json \
  --source-revision "$(git -C ../cloud-native rev-parse origin/main)"
python3 scripts/validate-mcp-catalog.py \
  --server-catalog /tmp/hermetiq-mcp-catalog.json \
  --server-provenance scripts/testdata/cloud-native-mcp-catalog.provenance.json
```

CI verifies the uncompressed fixture checksum and matches its source and
revision to the compact catalog. It cannot independently query whether that
recorded revision is still the tip of private `cloud-native`; the authenticated
refresh command above is therefore a required release step.

### Run the live canary suite (maintainers)

The canary suite needs Claude Code, an `ANTHROPIC_API_KEY` in the environment,
and a disposable MCP test deployment provisioned with the suite's fixtures.
It expects specific project names, telemetry states, and ConfigSets from
[`evals.json`](plugins/hermetiq/skills/hermetiq/evals/evals.json), including
**Local Demo** and **Local Dev**. One case creates a ConfigSet and Git commit in
the `local-dev` project; use a new test ConfigSet name and request UUID for each
run. Arbitrary production build IDs are not substitutes for these fixtures.

Set `HERMETIQ_MCP_EVAL_URL` to that test deployment's reachable endpoint. The runner
defaults to `http://127.0.0.1:5150/mcp`, but does not start a server or seed its data.
This repository does not provide a complete server/fixture provisioning procedure.
The runner supplies a URL without MCP authentication headers; its intended local
test runtime has MCP authentication disabled. Keep that configuration confined to
the isolated test environment. `ANTHROPIC_API_KEY` authenticates Claude, not the
Hermetiq MCP connection.

Load the API key using your normal secret-management workflow, then replace the
placeholders below with the provisioned fixtures and the catalog matching the
test server:

```bash
HERMETIQ_MCP_EVAL_URL=http://127.0.0.1:5150/mcp \
BUILD_ID='<fixture build ID>' \
INVOCATION_ID='<fixture invocation with profile and no miss groups or failed tests>' \
FAILURE_INVOCATION_ID='<fixture invocation with a remote failure and failed actions>' \
SIZECLASS_PROBE_INVOCATION_ID='<successful invocation with failed size-class probes>' \
REMOTE_EXEC_INVOCATION_ID='<remote-capacity fixture invocation>' \
LOCAL_INVOCATION_ID='<invocation with remote execution disabled>' \
CONFIG_SET_NAME='<new test ConfigSet name>' REQUEST_ID='<new request UUID>' \
python3 scripts/run-mcp-evals.py \
  --server-catalog /path/to/test-server-catalog.json \
  --output /tmp/hermetiq-skill-eval
```

The suite checks tool selection, response claims, and mutation handling. Use
`--case CASE_ID` (repeatable) to select cases. The runner writes raw/scored JSON per
case and an aggregate `run.json`, including prompts and tool results; it does not
write the API key. Running the local unit tests above does not run this live suite.
