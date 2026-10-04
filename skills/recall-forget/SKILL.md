---
name: recall-forget
description: "Forget something (Recall memory). Use only when the user explicitly invokes /recall-forget (or $recall-forget, /recall:recall-forget)."
argument-hint: "<memory or id>"
disable-model-invocation: true
---

Forget this from the user's long-term memory: the text the user gave with this command ($ARGUMENTS)

Call the `forget` tool of the `recall` MCP server with that description or memory id
(or run `recall forget "<description or id>"`). If several memories could match, list them
and ask which one first. Then tell the user exactly which memory was forgotten.
