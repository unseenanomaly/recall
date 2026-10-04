Change how Recall handles the user changing something they told you before.
Argument: $1

- on: auto-yes. Never ask "has that changed?"; the newest statement simply wins.
- off: ask first (the default).
- empty or status: just report the current setting.

Call the `settings` tool of the `recall` MCP server with auto_confirm true (on) or false (off),
or with no arguments for the status (or run `recall auto on`, `recall auto off`, `recall auto`).
Report the resulting setting in one sentence.
