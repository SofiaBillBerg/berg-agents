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
        history.push({role: "user", content: prompt});
    }
    if (answer.trim() !== "") {
        history.push({role: "assistant", content: answer});
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
    toolCalls?: Array<{
        tool: string;
        input?: string;
        output?: string;
        state?: string;
    }>;
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
            for (const call of msg.toolCalls ?? []) {
                lines.push(`**🔧 ${call.tool}**`, "");
                if (call.input) {
                    lines.push("```json", call.input, "```", "");
                }
                if (call.output) {
                    lines.push("```", call.output, "```", "");
                }
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

    // 3. Pending human review
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
