---
name: recall-show
description: "Show everything Recall currently believes (Recall memory). Use only when the user explicitly invokes /recall-show (or $recall-show, /recall:recall-show)."
disable-model-invocation: true
---

Show the user what Recall currently believes about them.

Call the `context` tool of the `recall` MCP server with no query (or run `recall context`).
Present it as a short list, followed by any open questions and disputed items. Don't add
anything that isn't in the result.
