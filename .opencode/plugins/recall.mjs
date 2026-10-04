// Recall for OpenCode: long-term memory that ages facts, asks before it overwrites
// what you said, and catches contradictions (including the model's own).
//
// Works three ways: `recall install opencode`, an npm/path entry in opencode.json,
// or opening the Recall repo itself. Needs the `recall` command on PATH.
// One default export serves both plugin APIs: OpenCode 2 reads `id` + `setup`,
// OpenCode 1 calls `server()`.

import { execFile, execFileSync } from "node:child_process";

const RECALL = ["recall"];
const COMMANDS = [
  {
    "name": "recall-remember",
    "description": "Save something to long-term memory",
    "template": "Save this to the user's long-term memory with Recall: $ARGUMENTS\n\n1. Call the `remember` tool of the `recall` MCP server with that text, in the user's words.\n   (No MCP tools available? Run `recall add \"<text>\" --json` in the shell.)\n2. If the result contains a question (\"You said before that ... Has that changed?\"), ask the\n   user exactly that question and wait for the reply. Then call `answer` with yes or no\n   (or run `recall answer yes` / `recall answer no`).\n3. Otherwise confirm in one short sentence what was saved, and mention anything it replaced.\nNever save passwords, API keys or tokens."
  },
  {
    "name": "recall-search",
    "description": "Ask what Recall remembers about something",
    "template": "Look up what Recall remembers about: $ARGUMENTS\n\nCall the `search` tool of the `recall` MCP server (or run `recall ask \"<topic>\" --json`).\nAnswer from the results in a few lines, with their \"as of\" dates. Say if something is marked\ndisputed or faded, and say plainly if nothing is remembered."
  },
  {
    "name": "recall-forget",
    "description": "Forget something",
    "template": "Forget this from the user's long-term memory: $ARGUMENTS\n\nCall the `forget` tool of the `recall` MCP server with that description or memory id\n(or run `recall forget \"<description or id>\"`). If several memories could match, list them\nand ask which one first. Then tell the user exactly which memory was forgotten."
  },
  {
    "name": "recall-show",
    "description": "Show everything Recall currently believes",
    "template": "Show the user what Recall currently believes about them.\n\nCall the `context` tool of the `recall` MCP server with no query (or run `recall context`).\nPresent it as a short list, followed by any open questions and disputed items. Don't add\nanything that isn't in the result."
  },
  {
    "name": "recall-auto",
    "description": "Turn \"has that changed?\" questions off (auto-yes) or on",
    "template": "Change how Recall handles the user changing something they told you before.\nArgument: $ARGUMENTS\n\n- on: auto-yes. Never ask \"has that changed?\"; the newest statement simply wins.\n- off: ask first (the default).\n- empty or status: just report the current setting.\n\nCall the `settings` tool of the `recall` MCP server with auto_confirm true (on) or false (off),\nor with no arguments for the status (or run `recall auto on`, `recall auto off`, `recall auto`).\nReport the resulting setting in one sentence."
  },
  {
    "name": "recall-check",
    "description": "Check your last reply for contradictions",
    "template": "Check your previous reply for contradictions with what you said earlier and with what\nthe user told you.\n\nCall the `check` tool of the `recall` MCP server with the full text of your last reply\n(or run `recall check \"<text>\"`). If it reports conflicts, correct yourself explicitly\n(\"Correction: ...\") or tell the user which statement is right. If it's clean, say so in one line."
  }
];

function run(args) {
  return new Promise((resolve) => {
    execFile(RECALL[0], [...RECALL.slice(1), ...args], { timeout: 20000, windowsHide: true },
      (_err, stdout) => resolve(String(stdout || "")));
  });
}

async function hook(event, text) {
  try {
    return JSON.parse((await run(["hook", event, "--agent", "generic", "--queue", "--text",
      String(text || "").slice(0, 8000)])) || "{}");
  } catch {
    return {};
  }
}

function contextNow() {
  try {
    return execFileSync(RECALL[0], [...RECALL.slice(1), "context", "--budget", "400"],
      { timeout: 20000, windowsHide: true, stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "";
  }
}

export default {
  id: "recall",

  // OpenCode 2: commands, plus what Recall believes on every turn.
  async setup(ctx) {
    await ctx.command.transform((editor) => {
      for (const command of COMMANDS) {
        editor.add({
          name: command.name,
          description: command.description,
          execute: async ({ sessionID, prompt, delivery }) => {
            await ctx.session.prompt({
              ...prompt,
              sessionID,
              text: command.template.replaceAll("$ARGUMENTS", (prompt && prompt.text) || ""),
              delivery,
            });
          },
        });
      }
    });
    await ctx.session.hook("context", (event) => {
      const text = contextNow();
      if (text) event.system.push({ type: "text", text: `<recall-memory>\n${text}\n</recall-memory>` });
    });
  },

  // OpenCode 1: commands + MCP server, memory on every message, reply checks.
  async server() {
    const started = new Set();      // sessions that already got the full memory block
    const pending = new Map();      // sessionID -> context for the next model call
    const assistantIds = new Set(); // ids of messages written by the assistant
    const lastText = new Map();     // sessionID -> latest assistant text

    return {
      config: async (config) => {
        config.command = config.command || {};
        for (const command of COMMANDS) {
          if (!config.command[command.name]) {
            config.command[command.name] = { description: command.description, template: command.template };
          }
        }
        config.mcp = config.mcp || {};
        if (!config.mcp.recall) {
          config.mcp.recall = { type: "local", command: [...RECALL, "mcp"], enabled: true };
        }
      },

      // The user sent a message: record personal facts / answers, fetch relevant memory.
      "chat.message": async (input, output) => {
        const text = (output.parts || [])
          .filter((p) => p.type === "text" && !p.synthetic)
          .map((p) => p.text)
          .join("\n");
        const parts = [];
        if (!started.has(input.sessionID)) {
          started.add(input.sessionID);
          const s = await hook("session-start", "");
          if (s.context) parts.push(s.context);
        }
        if (text) {
          const r = await hook("prompt", text);
          if (r.context) parts.push(r.context);
        }
        if (parts.length) pending.set(input.sessionID, parts.join("\n\n"));
      },

      // Hand that memory to the model with the system prompt.
      "experimental.chat.system.transform": async (input, output) => {
        const ctx = input.sessionID && pending.get(input.sessionID);
        if (ctx) {
          output.system.push(ctx);
          pending.delete(input.sessionID);
        }
      },

      // When the assistant finishes, check its reply for contradictions (raised next turn).
      event: async ({ event }) => {
        const props = event.properties || {};
        if (event.type === "message.updated" && props.info && props.info.role === "assistant") {
          assistantIds.add(props.info.id);
        } else if (event.type === "message.part.updated") {
          const p = props.part;
          if (p && p.type === "text" && assistantIds.has(p.messageID)) lastText.set(p.sessionID, p.text);
        } else if (event.type === "session.idle") {
          const id = props.sessionID;
          const text = id && lastText.get(id);
          if (text) {
            lastText.delete(id);
            await hook("stop", text);
          }
        }
      },
    };
  },
};
