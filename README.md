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

### Manual MCP server setup

To configure the MCP server without the plugin, add this to your Claude Code MCP settings:

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

## Install in Claude Desktop

### 1. Add the MCP server

Go to **Settings > Connectors** and add:

```
https://mcp.cloud-usc1.hermetiq.io
```

### 2. Package and upload the skill

```bash
git clone https://github.com/Hermetiq/hermetiq-ai-plugin
cd hermetiq-ai-plugin/plugins/hermetiq/skills
zip -r hermetiq.zip hermetiq/
```

> The zip must preserve the folder structure — it should contain `hermetiq/SKILL.md`, not a bare `SKILL.md` at the root.

Then in Claude Desktop:

1. Go to **Customize > Skills**
2. Click **+** > **Upload a skill**
3. Select `hermetiq.zip`

### 3. Enable code execution

Go to **Settings > Capabilities** and toggle on **Code execution and file creation**.

> Skills require a **Pro**, **Max**, **Team**, or **Enterprise** plan.

## Install in Codex

### 1. Add the MCP server

```bash
codex mcp add hermetiq --url https://mcp.cloud-usc1.hermetiq.io
```

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
mkdir -p ~/.codex/skills/hermetiq
cp -R plugins/hermetiq/skills/hermetiq/* ~/.codex/skills/hermetiq/
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
| `SKILL.md` | Core skill with playbooks for build analysis, cache optimization, RBE tuning, and infrastructure debugging |
| `references/REFERENCE.md` | Hermetiq data model, MCP tool inventory, and build configuration reference |
| `references/BUILDBARN_TUNING.md` | Buildbarn infrastructure tuning guide for storage, workers, and scheduler |
