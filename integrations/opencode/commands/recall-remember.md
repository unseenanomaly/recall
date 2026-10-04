---
description: "Save something to long-term memory"
---
Save this to the user's long-term memory with Recall: $ARGUMENTS

1. Call the `remember` tool of the `recall` MCP server with that text, in the user's words.
   (No MCP tools available? Run `recall add "<text>" --json` in the shell.)
2. If the result contains a question ("You said before that ... Has that changed?"), ask the
   user exactly that question and wait for the reply. Then call `answer` with yes or no
   (or run `recall answer yes` / `recall answer no`).
3. Otherwise confirm in one short sentence what was saved, and mention anything it replaced.
Never save passwords, API keys or tokens.
