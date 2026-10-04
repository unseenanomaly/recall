"""What ``recall install <agent>`` writes, agent by agent.

Each ``plan_*`` function returns the list of reversible actions for one agent. Paths
come from each tool's documentation (checked October 2026) and honour the tools' own
override variables (``CODEX_HOME``, ``COPILOT_HOME``, ``GROK_HOME``...).
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from importlib import resources
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .. import __version__
from ._fs import Action, File, Files, JsonEntry, JsonHooks, Manual, Note, Run, TextBlock, Tree
from .content import COMMANDS, INSTRUCTIONS_BLOCK, SKILL, body

DESCRIPTION = ("Long-term memory that ages facts, asks before it overwrites what you said, "
               "and catches contradictions, including the AI's own.")


@dataclass
class Ctx:
    """Where to install, and how agents should launch Recall."""

    home: str
    launcher: List[str]
    env: Mapping[str, str] = field(default_factory=dict)
    windows: bool = os.name == "nt"

    def path(self, *parts: str) -> str:
        return os.path.join(self.home, *parts)

    def dir(self, var: str, *default: str) -> str:
        v = self.env.get(var)
        return os.path.abspath(os.path.expanduser(v)) if v else self.path(*default)

    def xdg(self, *parts: str) -> str:
        base = self.env.get("XDG_CONFIG_HOME")
        return os.path.join(os.path.expanduser(base), *parts) if base else self.path(".config", *parts)

    # --- launching Recall from other tools -----------------------------------
    def _exe(self) -> str:
        exe = self.launcher[0]
        return exe.replace("\\", "/") if self.windows else exe

    def shell(self, *args: str) -> str:
        """A command string that works in sh, bash, zsh, cmd and (without spaces) PowerShell."""
        parts = [self._exe(), *self.launcher[1:], *args]
        return " ".join(f'"{p}"' if re.search(r"[\s&|<>()^;'$`]", p) else p for p in parts)

    def powershell(self, *args: str) -> str:
        parts = [self._exe(), *self.launcher[1:], *args]
        quoted = [f"'{p}'" if re.search(r"[\s&|<>()^;$`]", p) else p for p in parts]
        return ("& " if quoted[0].startswith("'") else "") + " ".join(quoted)

    def mcp(self) -> Dict[str, object]:
        return {"command": self.launcher[0], "args": [*self.launcher[1:], "mcp"]}

    def hook(self, event: str, agent: str) -> str:
        return self.shell("hook", event, "--agent", agent)


def default_launcher() -> List[str]:
    """Absolute path of the `recall` executable if it's on PATH, else `python -m recall`.
    Absolute paths keep working in GUI apps that don't inherit your shell's PATH."""
    import shutil
    exe = shutil.which("recall")
    return [os.path.abspath(exe)] if exe else [sys.executable, "-m", "recall"]


def template(name: str, launcher: Sequence[str]) -> str:
    # one joinpath() argument at a time: Python 3.9/3.10 accept only one
    text = resources.files("recall.integrations").joinpath("templates").joinpath(name).read_text(encoding="utf-8")
    return text.replace("__LAUNCHER__", json.dumps(list(launcher)))


def _frontmatter(**kv: str) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v)}" for k, v in kv.items() if v] + ["---", ""]
    return "\n".join(lines)


def markdown_commands(args_token: str, prefix: str = "", hint_key: str = "argument-hint") -> Dict[str, str]:
    out = {}
    for c in COMMANDS:
        fm = {"description": c.description}
        if c.hint and hint_key:
            fm[hint_key] = c.hint
        out[f"{prefix}{c.name}.md"] = _frontmatter(**fm) + body(c, args_token) + "\n"
    return out


def _mcp_toml(ctx: Ctx) -> str:
    def lit(s: str) -> str:
        return "'" + s + "'" if "'" not in s else json.dumps(s)
    args = ", ".join(lit(a) for a in [*ctx.launcher[1:], "mcp"])
    return f"[mcp_servers.recall]\ncommand = {lit(ctx.launcher[0])}\nargs = [{args}]\n"


def _toml_guard(outside: str) -> None:
    if re.search(r"^\s*\[mcp_servers\.recall\]", outside, re.M):
        raise Manual("it already defines [mcp_servers.recall]")
    if re.search(r"^\s*mcp_servers\s*=", outside, re.M):
        raise Manual("it uses an inline `mcp_servers = {...}` table")


def _claude_hooks(ctx: Ctx, agent: str, timeout: int = 15) -> Dict[str, list]:
    def h(event: str) -> list:
        return [{"hooks": [{"type": "command", "command": ctx.hook(event, agent), "timeout": timeout}]}]
    return {"SessionStart": h("session-start"), "UserPromptSubmit": h("prompt"), "Stop": h("stop")}


def _skill_tree(root: str) -> Tree:
    return Tree(root, {"SKILL.md": SKILL}, label="(skill: /recall, $recall)")


# ===================================================================== plans
def plan_claude_code(ctx: Ctx) -> List[Action]:
    """A Claude Code plugin saved under ~/.claude/skills/recall (a "skills-directory plugin")."""
    root = os.path.join(ctx.dir("CLAUDE_CONFIG_DIR", ".claude"), "skills", "recall")
    return [Tree(root, claude_plugin_files(ctx), label="(plugin: MCP + hooks + /recall:* commands)")]


def claude_plugin_files(ctx: Ctx) -> Dict[str, str]:
    files = {
        ".claude-plugin/plugin.json": json.dumps({
            "name": "recall", "displayName": "Recall", "version": __version__, "description": DESCRIPTION,
            "author": {"name": "Recall contributors"}, "license": "MIT",
            "keywords": ["memory", "contradictions", "mcp", "hooks"]}, indent=2) + "\n",
        ".mcp.json": json.dumps({"mcpServers": {"recall": ctx.mcp()}}, indent=2) + "\n",
        "hooks/hooks.json": json.dumps({
            "description": "Recall: inject memory, record personal facts, catch contradictions",
            "hooks": _claude_hooks(ctx, "claude-code")}, indent=2) + "\n",
    }
    for name, text in markdown_commands("$ARGUMENTS").items():
        files[f"commands/{name}"] = text
    return files


def plan_codex(ctx: Ctx) -> List[Action]:
    home = ctx.dir("CODEX_HOME", ".codex")
    return [
        TextBlock(os.path.join(home, "config.toml"), _mcp_toml(ctx), "#", _toml_guard, label="(MCP server)"),
        JsonHooks(os.path.join(home, "hooks.json"), _claude_hooks(ctx, "codex", 15), "--agent codex"),
        _skill_tree(ctx.path(".agents", "skills", "recall")),
        Note("Codex asks you to review new hooks once: open Codex, run /hooks, and trust the three "
             "Recall hooks. (On Codex versions where hooks are still behind a flag, also add "
             "`[features] codex_hooks = true` to config.toml.)"),
    ]


def gemini_extension_files(ctx: Ctx) -> Dict[str, str]:
    def h(event: str, name: str) -> list:
        return [{"hooks": [{"name": name, "type": "command", "command": ctx.hook(event, "gemini-cli"),
                            "timeout": 15000}]}]
    files = {
        "gemini-extension.json": json.dumps({
            "name": "recall", "version": __version__, "description": DESCRIPTION,
            "mcpServers": {"recall": ctx.mcp()}, "contextFileName": "GEMINI.md"}, indent=2) + "\n",
        "GEMINI.md": INSTRUCTIONS_BLOCK,
        "hooks/hooks.json": json.dumps({"hooks": {
            "SessionStart": h("session-start", "recall-session"),
            "BeforeAgent": h("prompt", "recall-prompt"),
            "AfterAgent": h("stop", "recall-check")}}, indent=2) + "\n",
    }
    for c in COMMANDS:
        prompt = body(c, "{{args}}")
        files[f"commands/recall/{c.name}.toml"] = (
            f"description = {json.dumps(c.description)}\nprompt = '''\n{prompt}\n'''\n")
    return files


def plan_gemini_cli(ctx: Ctx) -> List[Action]:
    root = ctx.path(".gemini", "extensions", "recall")
    return [Tree(root, gemini_extension_files(ctx), label="(extension: MCP + hooks + /recall:* commands)"),
            Note("Check it loaded with `gemini extensions list`. If hooks don't fire on an older Gemini CLI, "
                 "enable hooks in ~/.gemini/settings.json (see `/hooks`).")]


def plan_gemini(ctx: Ctx) -> List[Action]:
    """Gemini Code Assist agent mode (VS Code / JetBrains) reads ~/.gemini like the CLI."""
    return [
        JsonEntry(ctx.path(".gemini", "settings.json"), ("mcpServers", "recall"), ctx.mcp()),
        TextBlock(ctx.path(".gemini", "GEMINI.md"), INSTRUCTIONS_BLOCK, "html", label="(instructions)"),
        Note("Reload your IDE window so Gemini Code Assist picks up the MCP server."),
    ]


def plan_cursor(ctx: Ctx) -> List[Action]:
    home = ctx.path(".cursor")
    hooks = {
        "sessionStart": [{"command": ctx.hook("session-start", "cursor")}],
        "beforeSubmitPrompt": [{"command": ctx.hook("prompt", "cursor")}],
        "afterAgentResponse": [{"command": ctx.hook("response", "cursor")}],
        "stop": [{"command": ctx.hook("stop", "cursor")}],
    }
    actions: List[Action] = [
        JsonEntry(os.path.join(home, "mcp.json"), ("mcpServers", "recall"), ctx.mcp()),
        JsonHooks(os.path.join(home, "hooks.json"), hooks, "--agent cursor", seed={"version": 1}),
    ]
    actions.append(Files({os.path.join(home, "commands", n): t for n, t in markdown_commands(
        "the text the user typed after this command", "recall-", "").items()}, label="(/recall-* commands)"))
    actions.append(_skill_tree(os.path.join(home, "skills", "recall")))
    return actions


def plan_copilot(ctx: Ctx) -> List[Action]:
    home = ctx.dir("COPILOT_HOME", ".copilot")

    def h(event: str) -> list:
        return [{"type": "command", "bash": ctx.hook(event, "copilot"),
                 "powershell": ctx.powershell("hook", event, "--agent", "copilot"), "timeoutSec": 15}]
    hooks = {"version": 1, "hooks": {"sessionStart": h("session-start"), "userPromptSubmitted": h("prompt"),
                                     "agentStop": h("stop")}}
    return [
        JsonEntry(os.path.join(home, "mcp-config.json"), ("mcpServers", "recall"),
                  {"type": "local", **ctx.mcp(), "tools": ["*"]}),
        File(os.path.join(home, "hooks", "recall.json"), json.dumps(hooks, indent=2) + "\n", label="(hooks)"),
        _skill_tree(os.path.join(home, "skills", "recall")),
    ]


def plan_pi(ctx: Ctx) -> List[Action]:
    home = ctx.dir("PI_CODING_AGENT_DIR", ".pi", "agent")
    return [File(os.path.join(home, "extensions", "recall.ts"), template("pi.ts.tmpl", ctx.launcher),
                 label="(extension: memory each turn + /recall-* commands)"),
            Note("Restart pi to load the extension.")]


def _opencode_config(home: str) -> str:
    for name in ("opencode.json", "opencode.jsonc"):
        if os.path.exists(os.path.join(home, name)):
            return os.path.join(home, name)
    return os.path.join(home, "opencode.json")


def plan_opencode(ctx: Ctx) -> List[Action]:
    home = ctx.xdg("opencode")
    actions: List[Action] = [
        JsonEntry(_opencode_config(home), ("mcp", "recall"),
                  {"type": "local", "command": [*ctx.launcher, "mcp"], "enabled": True},
                  seed={"$schema": "https://opencode.ai/config.json"}),
        File(os.path.join(home, "plugins", "recall.js"), template("opencode.js.tmpl", ctx.launcher),
             label="(plugin: memory each turn + contradiction check)"),
    ]
    actions.append(Files({os.path.join(home, "commands", n): t for n, t in markdown_commands(
        "$ARGUMENTS", "recall-", "").items()}, label="(/recall-* commands)"))
    actions.append(_skill_tree(os.path.join(home, "skills", "recall")))
    return actions


def plan_antigravity(ctx: Ctx) -> List[Action]:
    root = ctx.path(".gemini", "config", "plugins", "recall")
    files = {
        "plugin.json": json.dumps({"name": "recall", "description": DESCRIPTION}, indent=2) + "\n",
        "mcp_config.json": json.dumps({"mcpServers": {"recall": ctx.mcp()}}, indent=2) + "\n",
        "hooks.json": json.dumps({"recall": {"Stop": [{"hooks": [
            {"type": "command", "command": ctx.hook("stop", "antigravity"), "timeout": 15}]}]}}, indent=2) + "\n",
        "skills/recall/SKILL.md": SKILL,
    }
    return [Tree(root, files, label="(plugin: MCP + stop hook + /recall skill)"),
            Note("If `agy plugin list` doesn't show it, run `agy plugin install ~/.gemini/config/plugins/recall`.")]


def plan_hermes(ctx: Ctx) -> List[Action]:
    home = ctx.dir("HERMES_HOME", ".hermes")
    plugin_yaml = (f"name: recall\nversion: {__version__}\ndescription: {json.dumps(DESCRIPTION)}\n"
                   "provides_hooks:\n  - pre_llm_call\n  - post_llm_call\n")
    mcp_yaml = ("mcp_servers:\n  recall:\n"
                f"    command: {json.dumps(ctx.launcher[0])}\n"
                f"    args: {json.dumps([*ctx.launcher[1:], 'mcp'])}\n")
    return [
        Tree(os.path.join(home, "plugins", "recall"),
             {"plugin.yaml": plugin_yaml, "__init__.py": template("hermes_plugin.py.tmpl", ctx.launcher)},
             label="(plugin: memory each turn + /recall-* commands)"),
        _skill_tree(os.path.join(home, "skills", "recall")),
        Run(["hermes", "plugins", "enable", "recall"], ["hermes", "plugins", "disable", "recall"],
            why="or add `recall` under plugins.enabled in ~/.hermes/config.yaml"),
        Note("Optional, for the MCP tools: add this to ~/.hermes/config.yaml, then /reload-mcp:\n" + mcp_yaml,
             on_uninstall="If you added the optional `recall` entry under mcp_servers in "
                          "~/.hermes/config.yaml, delete it."),
    ]


def plan_swival(ctx: Ctx) -> List[Action]:
    home = ctx.xdg("swival")
    actions: List[Action] = [
        TextBlock(os.path.join(home, "config.toml"), _mcp_toml(ctx), "#", _toml_guard, label="(MCP server)"),
        TextBlock(os.path.join(home, "AGENTS.md"), INSTRUCTIONS_BLOCK, "html", label="(instructions)"),
    ]
    actions.append(Files({os.path.join(home, "commands", f"recall-{c.name}.md"): body(c, "$1") + "\n"
                          for c in COMMANDS}, label="(!recall-* commands)"))
    actions.append(_skill_tree(os.path.join(home, "skills", "recall")))
    return actions


def plan_openclaw(ctx: Ctx) -> List[Action]:
    home = ctx.dir("OPENCLAW_STATE_DIR", ".openclaw")
    plugin = {
        "package.json": json.dumps({"name": "recall-openclaw", "version": __version__, "private": True,
                                    "type": "module", "openclaw": {"extensions": ["./index.ts"]}}, indent=2) + "\n",
        "openclaw.plugin.json": json.dumps({
            "id": "recall", "name": "Recall", "description": DESCRIPTION, "activation": {"onStartup": True},
            "configSchema": {"type": "object", "additionalProperties": False}}, indent=2) + "\n",
        "index.ts": template("openclaw.ts.tmpl", ctx.launcher),
    }
    return [
        JsonEntry(os.path.join(home, "openclaw.json"), ("mcp", "servers", "recall"), ctx.mcp()),
        Tree(os.path.join(home, "extensions", "recall"), plugin, label="(plugin: memory each turn + checks)"),
        _skill_tree(os.path.join(home, "skills", "recall")),
        Run(["openclaw", "plugins", "enable", "recall"], ["openclaw", "plugins", "disable", "recall"]),
        Note("For the contradiction check, allow the plugin to read replies: set "
             "plugins.entries.recall.hooks.allowConversationAccess to true in ~/.openclaw/openclaw.json."),
    ]


def plan_devin(ctx: Ctx) -> List[Action]:
    base = ctx.env.get("APPDATA") if ctx.windows and ctx.env.get("APPDATA") else None
    home = os.path.join(base, "devin") if base else ctx.xdg("devin")
    return [
        JsonEntry(os.path.join(home, "mcp_config.json"), ("mcpServers", "recall"), ctx.mcp()),
        JsonHooks(os.path.join(home, "config.json"), _claude_hooks(ctx, "devin"), "--agent devin"),
        _skill_tree(os.path.join(home, "skills", "recall")),
    ]


def plan_grok(ctx: Ctx) -> List[Action]:
    home = ctx.dir("GROK_HOME", ".grok")
    return [
        TextBlock(os.path.join(home, "config.toml"), _mcp_toml(ctx), "#", _toml_guard, label="(MCP server)"),
        File(os.path.join(home, "hooks", "recall.json"),
             json.dumps({"hooks": _claude_hooks(ctx, "grok")}, indent=2) + "\n", label="(hooks)"),
        _skill_tree(os.path.join(home, "skills", "recall")),
    ]


# ================================================================== registry
@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    plan: Callable[[Ctx], List[Action]]
    binaries: Tuple[str, ...]
    marker_dirs: Tuple[str, ...]        # home-relative folders that suggest it's installed
    provides: Tuple[str, ...]           # what Recall adds: mcp, hooks, commands, skill, plugin, instructions
    commands: str                       # how the slash commands look in this agent
    aliases: Tuple[str, ...] = ()


AGENTS: List[Agent] = [
    Agent("claude-code", "Claude Code", plan_claude_code, ("claude",), (".claude",),
          ("plugin", "mcp", "hooks", "commands"), "/recall:remember", ("claude",)),
    Agent("codex", "OpenAI Codex CLI", plan_codex, ("codex",), (".codex",),
          ("mcp", "hooks", "skill"), "$recall remember", ("openai-codex",)),
    Agent("gemini-cli", "Gemini CLI", plan_gemini_cli, ("gemini",), (".gemini",),
          ("extension", "mcp", "hooks", "commands", "instructions"), "/recall:remember"),
    Agent("gemini", "Gemini Code Assist (IDE agent mode)", plan_gemini, (), (".gemini",),
          ("mcp", "instructions"), "ask in chat", ("gemini-code-assist",)),
    Agent("cursor", "Cursor (IDE + cursor-agent CLI)", plan_cursor, ("cursor", "cursor-agent"), (".cursor",),
          ("mcp", "hooks", "commands", "skill"), "/recall-remember"),
    Agent("copilot", "GitHub Copilot CLI", plan_copilot, ("copilot",), (".copilot",),
          ("mcp", "hooks", "skill"), 'ask: "recall, remember ..."', ("copilot-cli", "github-copilot")),
    Agent("pi", "Pi coding agent", plan_pi, ("pi",), (".pi",),
          ("extension", "hooks", "commands"), "/recall-remember", ("pi-agent",)),
    Agent("opencode", "OpenCode", plan_opencode, ("opencode",), (".config/opencode",),
          ("mcp", "plugin", "commands", "skill"), "/recall-remember"),
    Agent("antigravity", "Antigravity CLI", plan_antigravity, ("agy", "antigravity"), (".gemini/antigravity-cli",),
          ("plugin", "mcp", "hooks", "skill"), "/recall remember", ("agy", "antigravity-cli")),
    Agent("hermes", "Hermes Agent", plan_hermes, ("hermes",), (".hermes",),
          ("plugin", "hooks", "commands", "skill"), "/recall-remember", ("hermes-agent",)),
    Agent("swival", "Swival", plan_swival, ("swival",), (".config/swival",),
          ("mcp", "commands", "skill", "instructions"), "!recall-remember"),
    Agent("openclaw", "OpenClaw", plan_openclaw, ("openclaw",), (".openclaw",),
          ("mcp", "plugin", "hooks", "skill"), "/recall remember  (or /skill recall)"),
    Agent("devin", "Devin CLI", plan_devin, ("devin",), (".config/devin",),
          ("mcp", "hooks", "skill"), "/recall remember", ("devin-cli",)),
    Agent("grok", "Grok Build", plan_grok, ("grok", "grok-build"), (".grok",),
          ("mcp", "hooks", "skill"), "/recall remember", ("grok-build",)),
]
BY_ID: Dict[str, Agent] = {a.id: a for a in AGENTS}
for _a in AGENTS:
    for _alias in _a.aliases:
        BY_ID.setdefault(_alias, _a)


def find(name: str) -> Optional[Agent]:
    return BY_ID.get(name.strip().lower().replace(" ", "-").replace("_", "-"))
