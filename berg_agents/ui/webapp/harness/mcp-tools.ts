import {callBackend} from "./specialists";

/**
 * MCP for the orchestrator: looking things up without delegating.
 *
 * Sofia's decision (2026-11-16): an advisor that can only read the files is half
 * an advisor — it should be able to fetch documentation, consult the code graph,
 * and reach her memory. Two tools rather than one per server, because the tools
 * and their arguments belong to the MCP SERVERS, and a hand-written copy of
 * their schemas would drift the day a server adds a tool:
 *
 * - `listMcpTools` — what is available, from berg's live toolsets.
 * - `useMcpTool` — call one of them.
 *
 * What may be called is decided in BERG (`AUTONOMOUS_MCP_SERVERS` and
 * `GITHUB_READ_TOOLS` in `ui/route_handlers/tools.py`), not here. The client
 * names a server and a tool; berg permits or refuses. That ordering matters
 * because these are the tools an agent that never asks for permission would be
 * running unattended, so the policy cannot live on the caller's side.
 */

/** One MCP tool, as berg's allowlisted list reports it. */
export interface McpToolSpec {
    server: string;
    tool: string;
    description: string;
}

/**
 * List the MCP tools the orchestrator may call directly.
 *
 * @returns The allowed tools, with what each does.
 */
export async function listMcpTools(): Promise<McpToolSpec[]> {
    "use step";
    const result = (await callBackend("/api/mcp/tools")) as {
        tools?: unknown;
    };
    const rows = Array.isArray(result.tools) ? result.tools : [];
    return rows.map((row) => {
        const entry = (row ?? {}) as Record<string, unknown>;
        return {
            server: String(entry.server ?? ""),
            tool: String(entry.tool ?? ""),
            description: String(entry.description ?? "")};
    });
}

/**
 * Call one MCP tool directly.
 *
 * @param server - The MCP server (for example ``context7``, ``codegraph``).
 * @param tool - The tool name, as listed by :func:`listMcpTools`.
 * @param args - The tool's arguments.
 * @returns The tool's output, and what ran.
 */
export async function useMcpTool(
    server: string,
    tool: string,
    args: Record<string, unknown> = {},
): Promise<string> {
    "use step";
    const result = (await callBackend(
        `/api/mcp/${encodeURIComponent(server)}/tools/${encodeURIComponent(tool)}`,
        {
            method: "POST",
            body: JSON.stringify({args})},
    )) as {output?: unknown};
    return String(result.output ?? "");
}