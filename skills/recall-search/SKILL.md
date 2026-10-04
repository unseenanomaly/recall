---
name: recall-search
description: "Ask what Recall remembers about something (Recall memory). Use only when the user explicitly invokes /recall-search (or $recall-search, /recall:recall-search)."
argument-hint: "<topic>"
disable-model-invocation: true
---

Look up what Recall remembers about: the text the user gave with this command ($ARGUMENTS)

Call the `search` tool of the `recall` MCP server (or run `recall ask "<topic>" --json`).
Answer from the results in a few lines, with their "as of" dates. Say if something is marked
disputed or faded, and say plainly if nothing is remembered.
