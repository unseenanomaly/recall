## Memory (Recall)

You have long-term memory through the `recall` MCP server (tools: remember, search, context,
answer, check, forget, settings). If the tools aren't available, use the `recall` CLI.

- When a task depends on the user's details, call `context` or `search` first.
- When the user states a lasting fact about themselves or the project, call `remember` with
  their words. If it returns a question ("You said before that ... Has that changed?"), ask it
  verbatim and record the reply with `answer`.
- If Recall reports that you contradicted yourself or the user, correct yourself plainly
  ("Correction: ...").
- Never store secrets.
