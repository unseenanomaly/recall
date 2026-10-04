"""The words Recall installs into agents: slash commands, the skill, and instructions.

Written once here and rendered into each agent's format (Markdown commands, Gemini
TOML, Swival templates, SKILL.md...), so every agent behaves the same way.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..mcp import INSTRUCTIONS

ARGS = "{ARGS}"   # replaced per agent: $ARGUMENTS, {{args}}, $1, ...


@dataclass(frozen=True)
class Command:
    name: str          # verb: /recall:<name> or /recall-<name>
    hint: str          # argument hint shown in menus
    description: str
    body: str          # prompt template; ARGS marks where the user's text goes


COMMANDS: List[Command] = [
    Command("remember", "<fact>", "Save something to long-term memory",
            f"""Save this to the user's long-term memory with Recall: {ARGS}

1. Call the `remember` tool of the `recall` MCP server with that text, in the user's words.
   (No MCP tools available? Run `recall add "<text>" --json` in the shell.)
2. If the result contains a question ("You said before that ... Has that changed?"), ask the
   user exactly that question and wait for the reply. Then call `answer` with yes or no
   (or run `recall answer yes` / `recall answer no`).
3. Otherwise confirm in one short sentence what was saved, and mention anything it replaced.
Never save passwords, API keys or tokens."""),
    Command("search", "<topic>", "Ask what Recall remembers about something",
            f"""Look up what Recall remembers about: {ARGS}

Call the `search` tool of the `recall` MCP server (or run `recall ask "<topic>" --json`).
Answer from the results in a few lines, with their "as of" dates. Say if something is marked
disputed or faded, and say plainly if nothing is remembered."""),
    Command("forget", "<memory or id>", "Forget something",
            f"""Forget this from the user's long-term memory: {ARGS}

Call the `forget` tool of the `recall` MCP server with that description or memory id
(or run `recall forget "<description or id>"`). If several memories could match, list them
and ask which one first. Then tell the user exactly which memory was forgotten."""),
    Command("show", "", "Show everything Recall currently believes",
            """Show the user what Recall currently believes about them.

Call the `context` tool of the `recall` MCP server with no query (or run `recall context`).
Present it as a short list, followed by any open questions and disputed items. Don't add
anything that isn't in the result."""),
    Command("auto", "[on|off|status]", 'Turn "has that changed?" questions off (auto-yes) or on',
            f"""Change how Recall handles the user changing something they told you before.
Argument: {ARGS}

- on: auto-yes. Never ask "has that changed?"; the newest statement simply wins.
- off: ask first (the default).
- empty or status: just report the current setting.

Call the `settings` tool of the `recall` MCP server with auto_confirm true (on) or false (off),
or with no arguments for the status (or run `recall auto on`, `recall auto off`, `recall auto`).
Report the resulting setting in one sentence."""),
    Command("check", "", "Check your last reply for contradictions",
            """Check your previous reply for contradictions with what you said earlier and with what
the user told you.

Call the `check` tool of the `recall` MCP server with the full text of your last reply
(or run `recall check "<text>"`). If it reports conflicts, correct yourself explicitly
("Correction: ...") or tell the user which statement is right. If it's clean, say so in one line."""),
]


def body(cmd: Command, args_token: str) -> str:
    return cmd.body.replace(ARGS, args_token)


SKILL = """---
name: recall
description: The user's long-term memory (Recall). Use when the user types /recall or $recall, asks you to remember or forget something, asks what you know about them, states a lasting fact about themselves or their project, or when an answer depends on their details. Also use it to check your own answers for contradictions.
---

# Recall: long-term memory

Recall remembers what the user tells you across sessions and across every AI tool they use.
It ages facts, catches contradictions (including yours), and asks before it overwrites
anything the user said.

Use the `recall` MCP tools when they are available: `remember`, `search`, `context`,
`answer`, `check`, `forget`, `settings`. Otherwise run the `recall` CLI in a shell; every
command below has a CLI form.

## Commands

The user may type `/recall <command> ...` (or `$recall ...`):

| Command | Do this | CLI fallback |
|---|---|---|
| `remember <fact>` | `remember` with the user's words | `recall add "<fact>" --json` |
| `search <topic>` | `search` | `recall ask "<topic>" --json` |
| `forget <thing>` | `forget` | `recall forget "<thing>"` |
| `show` (or nothing) | `context` with no query | `recall context` |
| `auto on` / `auto off` | `settings` with auto_confirm true / false | `recall auto on` / `recall auto off` |
| `check` | `check` with your last reply | `recall check "<text>"` |

## Rules

- **"Has that changed?"** When `remember` returns a question, ask the user exactly that and
  record the reply with `answer` (yes = replace the old fact, no = keep it). Never decide for
  them. If the user turned on auto-yes (`auto on`), there are no questions.
- **Contradictions.** If Recall says you contradicted yourself or the user, correct it plainly
  ("Correction: ...") so the record is updated. Trust what the user said unless they confirm
  it changed.
- Treat items marked "unverified" or "faded" as uncertain.
- Never store secrets (passwords, API keys, tokens).
"""


INSTRUCTIONS_BLOCK = """## Memory (Recall)

You have long-term memory through the `recall` MCP server (tools: remember, search, context,
answer, check, forget, settings). If the tools aren't available, use the `recall` CLI.

- When a task depends on the user's details, call `context` or `search` first.
- When the user states a lasting fact about themselves or the project, call `remember` with
  their words. If it returns a question ("You said before that ... Has that changed?"), ask it
  verbatim and record the reply with `answer`.
- If Recall reports that you contradicted yourself or the user, correct yourself plainly
  ("Correction: ...").
- Never store secrets.
"""

__all__ = ["ARGS", "Command", "COMMANDS", "body", "SKILL", "INSTRUCTIONS", "INSTRUCTIONS_BLOCK"]
