---
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

Each command is also its own skill (`/recall-remember`, `$recall-remember`, or
`/recall:recall-remember`, depending on the tool). The user may also just type
`/recall <command> ...`:

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
