/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/**
 * Utility functions for the App component.
 * Extracted from App.tsx to reduce component complexity.
 */

/**
 * Extract the displayable assistant answer from a harness result.
 * Primary source is `result.implementation.answer`; fallbacks cover alternates.
 */
export function toAssistantAnswer(result: unknown): string {
  if (!result) return "";
  const r = result as Record<string, unknown>;
  const impl = r.implementation as Record<string, unknown> | undefined;
  if (impl && typeof impl.answer === "string" && impl.answer.trim() !== "") {
    return impl.answer;
  }
  for (const key of ["answer", "response", "output"] as const) {
    const val = r[key];
    if (typeof val === "string" && val.trim() !== "") {
      return val;
    }
  }
  return "";
}

/**
 * Build the visible chat transcript for a completed result.
 */
export function toTranscriptHistory(
  result: unknown,
  prompt: string,
): Array<{ role: string; content: string }> {
  const history: Array<{ role: string; content: string }> = [];
  const r = result as Record<string, unknown> | null;
  const answer = toAssistantAnswer(r);
  if (prompt.trim() !== "") {
    history.push({ role: "user", content: prompt });
  }
  if (answer.trim() !== "") {
    history.push({ role: "assistant", content: answer });
  }
  return history;
}

/**
 * One transcript message for export. `reasoning` carries the model's
 * chain-of-thought trace when the provider emitted one — it renders
 * as a blockquote so no thinking is lost in saved sessions.
 */
export interface ExportMessage {
  role: string;
  content: string;
  reasoning?: string;
  toolCalls?: Array<ExportToolCall>;
}

/**
 * One tool call for export, including work that ran *inside* it.
 *
 * `children` is not decoration: a delegated sub-agent's whole conversation
 * (its text, its reasoning, its own tool calls) lives there. The export used to
 * ignore it, so a delegation printed the dispatch call and silently dropped
 * everything the sub-agent actually did — the one thing berg is built to show.
 */
export interface ExportToolCall {
  tool: string;
  input?: string;
  output?: string;
  state?: string;
  /** Work that ran inside this call — a delegated sub-agent's own parts. */
  children?: {
    text?: string;
    reasoning?: string;
    toolCalls?: ExportToolCall[];
  };
}

/**
 * Render a fenced code block where every line belongs to a blockquote.
 *
 * A fence inside a `>` blockquote only parses when the prefix is on every line,
 * including the opening and closing markers — this is why it is a helper rather
 * than string interpolation at the call site.
 *
 * @param body - The code or text to fence.
 * @param language - Fence language, or empty for a plain fence.
 * @param quote - The blockquote prefix, already repeated to the right depth.
 * @returns The lines of the fenced block, prefixes applied.
 */
function fenced(body: string, language: string, quote: string): string[] {
  const out = [`${quote}\`\`\`${language}`.trimEnd()];
  for (const line of body.split("\n")) {
    out.push(`${quote}${line}`);
  }
  out.push(`${quote}\`\`\``);
  return out;
}

/**
 * Write one tool call, and any work nested inside it, as markdown.
 *
 * Depth is expressed as blockquote nesting (`>` per level) rather than headers,
 * so a delegation tree reads as one visually-contained block and survives being
 * pasted anywhere markdown is rendered. Code fences are indented by nothing —
 * fence content must stay flush or it stops being code.
 *
 * @param lines - The output buffer, appended to in place.
 * @param call - The tool call to write.
 * @param depth - Nesting level; 0 for a top-level call.
 */
function writeToolCall(
  lines: string[],
  call: ExportToolCall,
  depth: number,
): void {
  // One ">" per level puts the child inside the parent's blockquote.
  const quote = "> ".repeat(depth);
  const label = depth === 0 ? `**🔧 ${call.tool}**` : `**🔧 ${call.tool}**`;

  lines.push(`${quote}${label}`, "");

  if (call.state) {
    lines.push(`${quote}_state: ${call.state}_`, "");
  }
  // Every line of a fenced block must carry the quote prefix, not just the
  // fence markers — otherwise the body escapes the blockquote and the fence
  // stops parsing as code at all.
  if (call.input) {
    lines.push(...fenced(call.input, "json", quote), "");
  }
  if (call.output) {
    lines.push(...fenced(call.output, "", quote), "");
  }

  const nested = call.children;
  if (!nested) return;

  // The sub-agent's own words first, then its reasoning, then its calls —
  // the same order the transcript shows them in.
  if (nested.text && nested.text.trim() !== "") {
    lines.push(`${quote}**Sub-agent said:**`, "");
    for (const line of nested.text.trim().split("\n")) {
      lines.push(`${quote}${line}`);
    }
    lines.push("");
  }
  if (nested.reasoning && nested.reasoning.trim() !== "") {
    lines.push(`${quote}**🧠 Sub-agent thinking:**`, "");
    for (const line of nested.reasoning.trim().split("\n")) {
      lines.push(`${quote}> ${line}`);
    }
    lines.push("");
  }
  for (const child of nested.toolCalls ?? []) {
    writeToolCall(lines, child, depth + 1);
  }
}

/**
 * Build session export as markdown.
 */
export function buildExportMarkdown(
  transcript: Array<ExportMessage>,
  events: Array<{ type: string; data?: unknown }>,
  hitlRequest: unknown,
  cmdOutput: string | null,
): string {
  const lines: string[] = [
    "# Berg Agents session export",
    "",
    `_Exported ${new Date().toLocaleString()}_`,
    "",
    "---",
    ""];

  // 1. Conversation transcript (tool outputs ride inside content;
  // reasoning traces are quoted so saved sessions keep the thinking).
  if (transcript.length > 0) {
    lines.push("## Conversation", "");
    transcript.forEach((msg) => {
      const header =
        msg.role === "assistant"
          ? "🤖 **Assistant**"
          : msg.role === "user"
            ? "🧑 **You**"
            : msg.role === "system"
              ? "⚙️ **System**"
              : msg.role;
      lines.push(header, "", msg.content || "", "");
      if (msg.reasoning && msg.reasoning.trim() !== "") {
        lines.push("**🧠 Thinking:**", "");
        for (const line of msg.reasoning.trim().split("\n")) {
          lines.push(`> ${line}`);
        }
        lines.push("");
      }
      // Recursive, because a delegation nests: the sub-agent's text, reasoning
      // and own tool calls all ride inside the parent call's `children`.
      for (const call of msg.toolCalls ?? []) {
        writeToolCall(lines, call, 0);
      }
      lines.push("---", "");
    });
  }

  // 2. Full harness event feed
  if (events.length > 0) {
    lines.push("## Events", "");
    events.forEach((event, idx) => {
      const eventType = event?.type || "unknown";
      const eventData = event?.data ?? event;
      lines.push(
        `### Event ${idx + 1}: ${eventType}`,
        "",
        "```json",
        JSON.stringify(eventData, null, 2),
        "```",
        "",
      );
    });
    lines.push("---", "");
  }

  // 3. Pending user review
  if (hitlRequest != null) {
    lines.push("## Pending Human Review", "");
    const hitl = hitlRequest as Record<string, unknown>;
    lines.push(
      "**Status:** Awaiting approval",
      "",
      "**Reasons:**",
      ...(
        (Array.isArray(hitl.review_reasons)
          ? hitl.review_reasons
          : []) as string[]
      ).map((r: string) => `- ${r}`),
      "",
      `**Risk Level:** ${hitl.risk_level || "N/A"}`,
      "",
      `**Complexity:** ${hitl.complexity || "N/A"}`,
      "",
      "---",
      "",
    );
  }

  // 4. Command output
  if (cmdOutput) {
    lines.push("## Command Output", "");
    lines.push("Command output would be here", "", "---", "");
  }

  return lines.join("\n");
}

/**
 * Check if there's anything worth exporting.
 */
export function hasExportableContent(
  result: unknown,
  events: unknown[],
  hitlRequest: unknown,
  cmdOutput: string | null,
): boolean {
  return (
    result != null ||
    events.length > 0 ||
    hitlRequest != null ||
    cmdOutput != null
  );
}
