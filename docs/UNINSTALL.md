<p align="center"><img src="../assets/logo.png" width="72" alt=""></p>

<h1 align="center">Uninstalling Recall</h1>

<p align="center">
  Take Recall out of one tool, all of them, or your machine entirely.<br>
  <code>recall uninstall</code> removes exactly what <code>recall install</code> added, and nothing else.
</p>

<p align="center">
  <a href="#quick-version">Quick version</a> ·
  <a href="#per-tool">Per tool</a> ·
  <a href="#by-hand">By hand</a> ·
  <a href="#your-memory">Your memory</a> ·
  <a href="#removing-the-program">The program</a> ·
  <a href="../README.md">Back to README</a>
</p>

---

## Quick version

```bash
recall uninstall --all          # undo every `recall install` (your memory is kept)
recall forget-all --yes         # delete the memory file too
pipx uninstall recall-memory    # remove the program (or: pip uninstall recall-memory)
```

Installed a tool's plugin from GitHub instead? Remove it with that tool's own command
([table below](#installed-from-github-the-tools-own-plugin-system)). Not sure what's installed?
`recall agents` lists what `recall install` set up. Add `--dry-run` to any `recall uninstall` to see
what would be removed without touching anything.

> **How removal works.** Recall never replaces your config files. It adds one entry (an MCP server
> named `recall`, hooks whose command contains `recall hook … --agent <tool>`, a fenced
> `>>> recall >>>` block) or a folder of its own marked with a `.recall-managed` file. Uninstall
> removes those entries and folders and leaves everything else exactly as it was. A config file
> Recall created from scratch is deleted once it's empty again.
>
> The first time Recall edited an existing file it saved a copy next to it as
> `<file>.recall-backup`. Uninstall leaves these copies alone so you can compare; delete them once
> you're happy.

## Per tool

Restart the tool afterwards so it unloads Recall.

### Installed from GitHub (the tool's own plugin system)

| Tool | Remove with |
|---|---|
| **Claude Code** | `/plugin uninstall recall@recall`, then `/plugin marketplace remove recall` |
| **OpenAI Codex** | `codex plugin remove recall` (and, if you like, remove the marketplace in `/plugins`) |
| **GitHub Copilot CLI** | `copilot plugin uninstall recall`, then `copilot plugin marketplace remove recall` |
| **Gemini CLI** | `gemini extensions uninstall recall` |
| **Antigravity CLI** | `agy plugin uninstall recall` |
| **Devin CLI** | `devin plugins remove recall` |
| **Grok Build** | `grok plugin uninstall recall` (and drop `"recall"` from `[plugins] enabled` if you added it) |
| **Hermes Agent** | `hermes plugins remove recall` |
| **Pi** | `pi uninstall` with the package name `pi list` shows |
| **Swival** | `swival skills delete --global <name>` for `recall` and each `recall-*` skill (`swival skills list` shows them); add `--library` to drop the staged copy |
| **OpenCode** (npm package) | remove `recall-memory` from `plugin` / `plugins` in `opencode.json` |

These remove the plugin itself. If you also used `recall install` for the same tool, run the
matching `recall uninstall` below as well.

### Installed with `recall install`

| Tool | One command | What gets removed |
|---|---|---|
| **Claude Code** | `recall uninstall claude-code` | the plugin folder `~/.claude/skills/recall/` (MCP server, hooks, `/recall:*` commands) |
| **OpenAI Codex CLI** | `recall uninstall codex` | the `[mcp_servers.recall]` block in `~/.codex/config.toml` · Recall's 3 hooks in `~/.codex/hooks.json` · `~/.agents/skills/recall/` |
| **Gemini CLI** | `recall uninstall gemini-cli` | the extension folder `~/.gemini/extensions/recall/` |
| **Gemini Code Assist** | `recall uninstall gemini` | `mcpServers.recall` in `~/.gemini/settings.json` · the Recall block in `~/.gemini/GEMINI.md` |
| **Cursor** | `recall uninstall cursor` | `mcpServers.recall` in `~/.cursor/mcp.json` · Recall's 4 hooks in `~/.cursor/hooks.json` · `~/.cursor/commands/recall-*.md` · `~/.cursor/skills/recall/` |
| **GitHub Copilot CLI** | `recall uninstall copilot` | `mcpServers.recall` in `~/.copilot/mcp-config.json` · `~/.copilot/hooks/recall.json` · `~/.copilot/skills/recall/` |
| **Pi** | `recall uninstall pi` | `~/.pi/agent/extensions/recall.ts` |
| **OpenCode** | `recall uninstall opencode` | `mcp.recall` in `~/.config/opencode/opencode.json` · `~/.config/opencode/plugins/recall.js` · `~/.config/opencode/commands/recall-*.md` · `~/.config/opencode/skills/recall/` |
| **Antigravity CLI** | `recall uninstall antigravity` | the plugin folder `~/.gemini/config/plugins/recall/` |
| **Hermes Agent** | `recall uninstall hermes` | runs `hermes plugins disable recall` (when `hermes` is on PATH) · `~/.hermes/plugins/recall/` · `~/.hermes/skills/recall/` |
| **Swival** | `recall uninstall swival` | the Recall blocks in `~/.config/swival/config.toml` and `~/.config/swival/AGENTS.md` · `~/.config/swival/commands/recall-*.md` · `~/.config/swival/skills/recall/` |
| **OpenClaw** | `recall uninstall openclaw` | runs `openclaw plugins disable recall` (when `openclaw` is on PATH) · `mcp.servers.recall` in `~/.openclaw/openclaw.json` · `~/.openclaw/extensions/recall/` · `~/.openclaw/skills/recall/` |
| **Devin CLI** | `recall uninstall devin` | `mcpServers.recall` in `~/.config/devin/mcp_config.json` · Recall's 3 hooks in `~/.config/devin/config.json` · `~/.config/devin/skills/recall/` (on Windows: `%APPDATA%\devin\`) |
| **Grok Build** | `recall uninstall grok` | the `[mcp_servers.recall]` block in `~/.grok/config.toml` · `~/.grok/hooks/recall.json` · `~/.grok/skills/recall/` |

Paths follow each tool's own override variables when set (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
`COPILOT_HOME`, `PI_CODING_AGENT_DIR`, `HERMES_HOME`, `OPENCLAW_STATE_DIR`, `GROK_HOME`,
`XDG_CONFIG_HOME`). On Windows, `~` is `%USERPROFILE%`.

### Installed some other way?

| If you installed with… | Remove with… |
|---|---|
| `claude mcp add … recall` | `claude mcp remove recall` (add `--scope user` if you used it) |
| `codex mcp add recall …` | `codex mcp remove recall` |
| `gemini extensions link …` | `gemini extensions uninstall recall` |
| `gemini mcp add … recall` | `gemini mcp remove recall` |
| `devin mcp add … recall` | `devin mcp remove recall` |
| `openclaw plugins install …` | `openclaw plugins uninstall recall` |
| Copilot `/mcp add` | `/mcp` → remove `recall`, or delete it from `~/.copilot/mcp-config.json` |
| `pi --extension …` (one session) | nothing to remove; just stop passing the flag |

## By hand

If the `recall` command is already gone, delete these yourself. Everything Recall adds is named
`recall`, so it's easy to spot.

<details>
<summary><b>Claude Code</b></summary>

```bash
rm -rf ~/.claude/skills/recall
```
</details>

<details>
<summary><b>OpenAI Codex CLI</b></summary>

- `~/.codex/config.toml`: delete everything from `# >>> recall >>>` to `# <<< recall <<<`
- `~/.codex/hooks.json`: delete the hook entries whose `command` contains `hook … --agent codex`
- `rm -rf ~/.agents/skills/recall`
</details>

<details>
<summary><b>Gemini CLI</b></summary>

```bash
gemini extensions uninstall recall    # or: rm -rf ~/.gemini/extensions/recall
```
</details>

<details>
<summary><b>Gemini Code Assist</b></summary>

- `~/.gemini/settings.json`: delete `"recall"` from `mcpServers`
- `~/.gemini/GEMINI.md`: delete everything from `<!-- >>> recall >>> -->` to `<!-- <<< recall <<< -->`
</details>

<details>
<summary><b>Cursor</b></summary>

- `~/.cursor/mcp.json`: delete `"recall"` from `mcpServers`
- `~/.cursor/hooks.json`: delete the entries whose `command` contains `--agent cursor`
- `rm ~/.cursor/commands/recall-*.md && rm -rf ~/.cursor/skills/recall`
</details>

<details>
<summary><b>GitHub Copilot CLI</b></summary>

- `~/.copilot/mcp-config.json`: delete `"recall"` from `mcpServers`
- `rm ~/.copilot/hooks/recall.json && rm -rf ~/.copilot/skills/recall`
</details>

<details>
<summary><b>Pi</b></summary>

```bash
rm ~/.pi/agent/extensions/recall.ts
```
</details>

<details>
<summary><b>OpenCode</b></summary>

- `~/.config/opencode/opencode.json` (or `.jsonc`): delete `"recall"` from `mcp`
- `rm ~/.config/opencode/plugins/recall.js ~/.config/opencode/commands/recall-*.md`
- `rm -rf ~/.config/opencode/skills/recall`
</details>

<details>
<summary><b>Antigravity CLI</b></summary>

```bash
agy plugin uninstall recall           # if you installed it through agy
rm -rf ~/.gemini/config/plugins/recall
```
</details>

<details>
<summary><b>Hermes Agent</b></summary>

```bash
hermes plugins disable recall
rm -rf ~/.hermes/plugins/recall ~/.hermes/skills/recall
```

If you added the optional `recall` entry under `mcp_servers:` in `~/.hermes/config.yaml`, delete it
and run `/reload-mcp`.
</details>

<details>
<summary><b>Swival</b></summary>

- `~/.config/swival/config.toml` and `~/.config/swival/AGENTS.md`: delete the Recall blocks
  (`>>> recall >>>` … `<<< recall <<<`)
- `rm ~/.config/swival/commands/recall-*.md && rm -rf ~/.config/swival/skills/recall`
</details>

<details>
<summary><b>OpenClaw</b></summary>

```bash
openclaw plugins disable recall
rm -rf ~/.openclaw/extensions/recall ~/.openclaw/skills/recall
```

and delete `recall` from `mcp.servers` in `~/.openclaw/openclaw.json` (plus
`plugins.entries.recall` if you added it).
</details>

<details>
<summary><b>Devin CLI</b></summary>

- `~/.config/devin/mcp_config.json`: delete `"recall"` from `mcpServers` (or `devin mcp remove recall`)
- `~/.config/devin/config.json`: delete the hook entries whose `command` contains `--agent devin`
- `rm -rf ~/.config/devin/skills/recall`

On Windows the folder is `%APPDATA%\devin\`.
</details>

<details>
<summary><b>Grok Build</b></summary>

- `~/.grok/config.toml`: delete everything from `# >>> recall >>>` to `# <<< recall <<<`
- `rm ~/.grok/hooks/recall.json && rm -rf ~/.grok/skills/recall`
</details>

## Your memory

Uninstalling from tools **never** deletes what Recall remembers, so you can reinstall later and pick
up where you left off.

| To… | Run |
|---|---|
| see which memory file is in use | `recall where` |
| forget one thing | `recall forget "<description or id>"` |
| age everything and delete forgotten entries for good | `recall sweep --purge` |
| delete the whole memory | `recall forget-all --yes` |
| delete a project's own memory | `rm -rf .recall` in that project |
| delete everything Recall keeps | `rm -rf ~/.recall` (memory, settings, hook log, install record) |

## Removing the program

```bash
recall uninstall --all          # first, so no tool keeps calling a missing program
pipx uninstall recall-memory    # or: pip uninstall recall-memory
rm -rf ~/.recall                # optional: memory, settings and logs
```

Uninstalling the program first works too, but each tool will then report that it can't start the
`recall` MCP server or hook commands (they don't block your work). The [by-hand](#by-hand) list
cleans up afterwards.
