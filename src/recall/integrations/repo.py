"""The files that make the Recall repo installable straight from GitHub, in every agent.

The repository root doubles as a plugin / extension / package for each tool's own
installer, the way most agent plugins ship:

=======================  ==================================================  =============================
Tool                     Reads                                               Install command
=======================  ==================================================  =============================
Claude Code              .claude-plugin/{marketplace,plugin}.json            /plugin marketplace add OWNER/REPO
Codex                    .agents/plugins/marketplace.json, .codex-plugin/    codex plugin marketplace add OWNER/REPO
GitHub Copilot CLI       .github/plugin/{marketplace,plugin}.json            copilot plugin marketplace add OWNER/REPO
Devin CLI                .devin-plugin/plugin.json                           devin plugins install OWNER/REPO
Grok Build               .grok-plugin/marketplace.json                       grok plugin install OWNER/REPO --trust
Gemini CLI, Antigravity  gemini-extension.json + AGENTS.md + commands/       gemini extensions install URL
Hermes Agent             plugin.yaml + __init__.py                           hermes plugins install OWNER/REPO
Pi, OpenCode             package.json (pi / main), .opencode/plugins/        pi install git:github.com/OWNER/REPO
Swival                   skills/                                             swival skills add URL
=======================  ==================================================  =============================

Everything shares ``skills/``, ``.mcp.json`` and ``hooks/``. All of it is generated:
run ``recall export-repo`` after changing commands, skills, hooks or templates (the test
suite fails if the committed copies are stale).
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from .. import __version__
from .agents import (DESCRIPTION, Ctx, _claude_hooks, hermes_plugin_yaml, markdown_commands,
                     opencode_commands, plan_antigravity, plan_openclaw, template)
from .content import COMMANDS, INSTRUCTIONS_BLOCK, all_skills, body

PLACEHOLDER = "YOUR-GITHUB-USER/recall"
KEYWORDS = ["memory", "ai-agents", "contradiction-detection", "mcp", "hooks", "skills"]


def read_slug(pyproject: str) -> str:
    """OWNER/REPO from ``[project.urls] Repository`` in pyproject.toml."""
    try:
        with open(pyproject, encoding="utf-8") as f:
            m = re.search(r'^\s*Repository\s*=\s*"https://github\.com/([^"/]+/[^"/]+?)(?:\.git)?/?"',
                          f.read(), re.M)
        return m.group(1) if m else PLACEHOLDER
    except OSError:
        return PLACEHOLDER


def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def repo_files(slug: str = PLACEHOLDER) -> Dict[str, str]:
    owner, repo = slug.split("/", 1)
    url = f"https://github.com/{slug}"
    ctx = Ctx(home="/HOME", launcher=["recall"], windows=False)
    author = {"name": owner, "url": f"https://github.com/{owner}"}
    meta = {"name": "recall", "version": __version__, "description": DESCRIPTION, "author": author,
            "homepage": url, "repository": url, "license": "MIT", "keywords": KEYWORDS}
    entry = {"name": "recall", "description": DESCRIPTION, "source": "./", "category": "productivity"}
    marketplace = {"name": "recall", "description": "Recall: AI memory that forgets on purpose.",
                   "owner": author, "plugins": [entry]}
    files: Dict[str, str] = {}

    # shared by every plugin host
    files[".mcp.json"] = _json({"mcpServers": {"recall": ctx.mcp()}})
    files["hooks/claude-codex.json"] = _json({"hooks": _claude_hooks(ctx, "claude-code")})

    def copilot(event: str) -> list:
        cmd = f"recall hook {event} --agent copilot"
        return [{"type": "command", "bash": f"{cmd} || exit 0",
                 "powershell": f"if (Get-Command recall -ErrorAction SilentlyContinue) {{ {cmd} }}",
                 "timeoutSec": 15}]
    files["hooks/copilot.json"] = _json({"version": 1, "hooks": {
        "sessionStart": copilot("session-start"), "userPromptSubmitted": copilot("prompt"),
        "agentStop": copilot("stop")}})
    for name, text in all_skills().items():
        files[f"skills/{name}/SKILL.md"] = text

    # Claude Code (and Grok Build, which reads Claude plugin manifests)
    files[".claude-plugin/plugin.json"] = _json({**meta, "hooks": "./hooks/claude-codex.json"})
    files[".claude-plugin/marketplace.json"] = _json(
        {"$schema": "https://anthropic.com/claude-code/marketplace.schema.json", **marketplace})
    files[".grok-plugin/marketplace.json"] = _json(marketplace)

    # Codex
    files[".codex-plugin/plugin.json"] = _json({
        **meta, "skills": "./skills/", "hooks": "./hooks/claude-codex.json", "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": "Recall", "shortDescription": "Memory that asks before it overwrites you",
            "longDescription": DESCRIPTION, "developerName": owner, "category": "Productivity",
            "capabilities": ["Instructions", "Lifecycle hooks", "MCP"], "websiteURL": url,
            "defaultPrompt": ["What do you remember about me?", "Remember that I prefer pnpm.",
                              "Check your last answer for contradictions."],
            "brandColor": "#8B5CF6"}})
    files[".agents/plugins/marketplace.json"] = _json({
        "name": "recall", "interface": {"displayName": "Recall"},
        "plugins": [{"name": "recall", "source": {"source": "url", "url": f"{url}.git", "ref": "main"},
                     "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                     "category": "Productivity"}]})

    # GitHub Copilot CLI
    copilot_parts = {"commands": "commands/", "skills": "skills/", "hooks": "hooks/copilot.json"}
    files[".github/plugin/plugin.json"] = _json({**meta, **copilot_parts})
    files[".github/plugin/marketplace.json"] = _json(
        {**marketplace, "plugins": [{**entry, "tags": KEYWORDS, **copilot_parts}]})

    # Devin CLI (loads skills/ and .mcp.json from the plugin root) + Agent Plugins spec
    files[".devin-plugin/plugin.json"] = _json(meta)
    files["plugin.json"] = _json({"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                                  "name": "recall"})

    # Gemini CLI + Antigravity CLI (agy reuses gemini-extension.json)
    files["gemini-extension.json"] = _json({"name": "recall", "version": __version__, "description": DESCRIPTION,
                                            "mcpServers": {"recall": ctx.mcp()}, "contextFileName": "AGENTS.md"})
    files["AGENTS.md"] = INSTRUCTIONS_BLOCK
    for c in COMMANDS:
        files[f"commands/recall-{c.name}.toml"] = (
            f"description = {json.dumps(c.description)}\nprompt = '''\n{body(c, '{{args}}')}\n'''\n")

    # Hermes Agent (the repo root is the plugin; it can run the bundled src/ without pip)
    files["plugin.yaml"] = hermes_plugin_yaml() + "provides_skills:\n" + "".join(
        f"  - {n}\n" for n in all_skills())
    files["__init__.py"] = template("hermes_plugin.py.tmpl", ["recall"])

    # Pi (package.json "pi") and OpenCode (npm "main", or .opencode/plugins/ from a checkout)
    files["package.json"] = _json({
        "name": "recall-memory", "version": __version__, "description": DESCRIPTION,
        "keywords": ["opencode-plugin", "opencode", "pi-package", "pi", *KEYWORDS], "license": "MIT",
        "author": author, "homepage": url, "repository": {"type": "git", "url": f"git+{url}.git"},
        "bugs": {"url": f"{url}/issues"}, "type": "module",
        "main": "./.opencode/plugins/recall.mjs", "exports": {".": "./.opencode/plugins/recall.mjs"},
        "files": [".opencode/plugins/", "integrations/pi/", "skills/", "AGENTS.md", "LICENSE"],
        "pi": {"extensions": ["./integrations/pi/recall.ts"]},
        "publishConfig": {"access": "public"}})
    files[".opencode/plugins/recall.mjs"] = template("opencode.js.tmpl", ["recall"], COMMANDS=opencode_commands())
    files[".opencode/plugins/index.js"] = (
        "// OpenCode 2 loads index.js from .opencode/plugins/; npm users get recall.mjs via package.json.\n"
        'export { default } from "./recall.mjs";\n')

    # Ready-to-copy files for tools without a GitHub-native installer (see integrations/README.md)
    files["integrations/pi/recall.ts"] = template("pi.ts.tmpl", ["recall"])
    for plan, name in ((plan_openclaw, "openclaw"), (plan_antigravity, "antigravity")):
        for action in plan(ctx):
            root = getattr(action, "root", "").replace("\\", "/")
            if root.split("/")[-2:-1] in (["plugins"], ["extensions"]):
                for rel, text in action.files.items():
                    files[f"integrations/{name}/{rel}"] = text
    for rel, text in markdown_commands("the text the user typed after this command", "recall-", "").items():
        files[f"integrations/cursor/commands/{rel}"] = text
    for c in COMMANDS:
        files[f"integrations/swival/commands/recall-{c.name}.md"] = body(c, "$1") + "\n"
    files["integrations/README.md"] = INTEGRATIONS_README
    return files


INTEGRATIONS_README = """# integrations/

Generated by `recall export-repo`; don't edit by hand.

Most tools install Recall straight from this repository (see the README). This folder
holds the files for the rest, ready to copy:

| Folder | For | How |
|---|---|---|
| `pi/recall.ts` | Pi | used by `pi install git:...` through `package.json`; or `pi --extension ./integrations/pi/recall.ts` |
| `openclaw/` | OpenClaw | copy to `~/.openclaw/extensions/recall/` (or run `recall install openclaw`) |
| `antigravity/` | Antigravity CLI | `agy plugin install ./integrations/antigravity` for the stop-hook variant |
| `cursor/commands/` | Cursor | copy to `~/.cursor/commands/` (or run `recall install cursor`) |
| `swival/commands/` | Swival | copy to `~/.config/swival/commands/` (or run `recall install swival`) |

Every file here expects the `recall` command on your PATH.
"""


def export_repo(target: str, slug: Optional[str] = None) -> List[str]:
    slug = slug or read_slug(os.path.join(target, "pyproject.toml"))
    written = []
    for rel, text in repo_files(slug).items():
        path = os.path.join(target, *rel.split("/"))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(rel)
    return written
