/**
 * Recall for OpenClaw: long-term memory that ages facts, asks before it overwrites
 * what you said, and catches contradictions (including the model's own).
 *
 * Installed by `recall install openclaw`. Remove with `recall uninstall openclaw`.
 * The agent_end check needs conversation access:
 *   plugins.entries.recall.hooks.allowConversationAccess = true
 */
import { execFile } from "node:child_process";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const RECALL: string[] = ["recall"];

function hook(event: string, text: string): Promise<{ context?: string }> {
  return new Promise((resolve) => {
    execFile(
      RECALL[0],
      [...RECALL.slice(1), "hook", event, "--agent", "generic", "--queue", "--text", text.slice(0, 8000)],
      { timeout: 15000, windowsHide: true },
      (_err, stdout) => {
        try {
          resolve(JSON.parse(String(stdout || "{}")));
        } catch {
          resolve({});
        }
      },
    );
  });
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((c: any) => c && c.type === "text" && typeof c.text === "string")
      .map((c: any) => c.text)
      .join("\n");
  }
  return "";
}

export default definePluginEntry({
  id: "recall",
  name: "Recall",
  description: "Long-term memory that asks before it overwrites what you said and catches contradictions.",
  register(api: any) {
    const started = new Set<string>();

    api.on("before_prompt_build", async (event: any, ctx: any) => {
      const key = String(ctx?.sessionKey ?? ctx?.sessionId ?? "default");
      const parts: string[] = [];
      if (!started.has(key)) {
        started.add(key);
        const s = await hook("session-start", "");
        if (s.context) parts.push(s.context);
      }
      const r = await hook("prompt", String(event?.prompt ?? ""));
      if (r.context) parts.push(r.context);
      if (parts.length) return { prependContext: parts.join("\n\n") };
    });

    api.on("agent_end", async (event: any) => {
      const messages: any[] = event?.messages ?? [];
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i]?.role === "assistant") {
          const text = textOf(messages[i].content);
          if (text) await hook("stop", text);
          break;
        }
      }
    });
  },
});
