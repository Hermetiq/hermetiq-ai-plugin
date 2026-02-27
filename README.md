# Hermetiq Plugin for Claude Code

Bazel build optimization skill powered by [Hermetiq](https://hermetiq.com) analytics. 
Gives Claude Code (or the AI agent of your choosing) deep expertise in build performance, cache optimization, remote execution tuning, and Buildbarn infrastructure — backed by your project's real data via the Hermetiq MCP server.

## What it does

When installed, your AI agent gains the ability to:

- **Analyze builds** — diagnose slow builds, find critical path bottlenecks, and identify regressions
- **Fix cache misses** — pinpoint why actions miss cache and recommend targeted fixes
- **Optimize remote execution** — reduce queue wait, right-size workers, cut RBE costs
- **Debug infrastructure** — investigate Buildbarn storage, scheduler, and worker fleet health
- **Audit configuration** — review `.bazelrc` flags, hermeticity settings, and build graph patterns
- **Track trends** — compare build performance across time periods, branches, and teams

## Prerequisites

1. A [Hermetiq](https://dashboard.hermetiq.io) account with at least one project receiving BEP events

## Install in Claude Code

```bash
# Add the Hermetiq marketplace
/plugin marketplace add Hermetiq/hermetiq-ai-plugin

# Install the hermetiq skill
/plugin install hermetiq@hermetiq
```

The plugin automatically configures the Hermetiq MCP server connection. On first use, you'll authenticate via your Hermetiq account; login to https://dashboard.hermetiq.io prior to authenticating MCP for a more seamless experience.
Hermetiq MCP server supports OAuth2 Dynamic Client Registration (DCR) (via [Stytch](https://stytch.com/docs/connected-apps/guides/remote-mcp-servers))

### Manual MCP server setup

If you prefer to configure the MCP server manually (or use it without the plugin), add this to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "hermetiq": {
      "url": "https://mcp.cloud-usc1.hermetiq.io"
    }
  }
}
```

## Usage

Once installed, Claude Code will automatically activate the skill when you ask about build performance. You can also invoke it directly:

```
/hermetiq analyze my latest build
/hermetiq why is my cache hit rate dropping?
/hermetiq compare this week's builds to last week
/hermetiq what's causing slow queue times?
```

Or just ask naturally — Claude will use the skill when relevant:

```
Why did my build take 20 minutes today?
Show me cache miss trends for the last 7 days
Which targets are most expensive to execute remotely?
```

## Set up for Codex

The Hermetiq skill and MCP server work in Codex as well.

### 1) Add the Hermetiq MCP server via Codex Desktop > Settings > MCP Servers or `codex mcp` CLI

```bash
codex mcp add hermetiq --url https://mcp.cloud-usc1.hermetiq.io
```

Optional verification:

```bash
codex mcp get hermetiq
codex mcp list
```

### 2) Authenticate

If using Codex Desktop, click the Authenticate button (tip: login to https://dashboard.hermetiq.io prior to authenticating MCP for a more seamless experience)

```bash
codex mcp login hermetiq
```

For MCP authentication details in Codex, see: [Codex MCP](https://developers.openai.com/codex/mcp)

### 3) Install the Hermetiq skill for Codex

Clone this repo locally and then copy the skill into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills/hermetiq
cp -R plugins/hermetiq/skills/hermetiq/* ~/.codex/skills/hermetiq/
```

The installed skill entrypoint is:

```text
~/.codex/skills/hermetiq/SKILL.md
```

### 4) Restart Codex

Restart Codex so it reloads MCP server and skill definitions.

### 5) Use it

In Codex, ask build-performance questions naturally or invoke the skill by name:

```text
Use the hermetiq skill to analyze my latest build
Why is remote execution queue time high this week?
Show cache miss reasons by mnemonic for my failing builds
```

## What's included

| File | Description |
|------|-------------|
| `SKILL.md` | Core skill definition with playbooks for build analysis, cache optimization, RBE tuning, and infrastructure debugging |
| `references/REFERENCE.md` | Hermetiq data model, MCP tool inventory, and build configuration reference |
| `references/BUILDBARN_TUNING.md` | Buildbarn infrastructure tuning guide for storage, workers, and scheduler |
