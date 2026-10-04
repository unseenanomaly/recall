---
name: recall-check
description: "Check your last reply for contradictions (Recall memory). Use only when the user explicitly invokes /recall-check (or $recall-check, /recall:recall-check)."
disable-model-invocation: true
---

Check your previous reply for contradictions with what you said earlier and with what
the user told you.

Call the `check` tool of the `recall` MCP server with the full text of your last reply
(or run `recall check "<text>"`). If it reports conflicts, correct yourself explicitly
("Correction: ...") or tell the user which statement is right. If it's clean, say so in one line.
