import { callBackend } from "./specialists";

/**
 * The orchestrator's own tools: looking at the project itself.
 *
 * An advisor that cannot read the code it advises on is a dispatcher wearing an
 * advisor's title — it can only repeat what a specialist told it, which is
 * exactly the complaint Sofia raised ("it's awkward when the orchestrator can't
 * actually read the files and only has to rely on specialists reporting"). These
 * close that gap for the cheap cases: read a file, list a directory, search the
 * code. No specialist is started, no run is spawned, no turn is spent.
 *
 * READ-ONLY, and that is the whole design:
 *
 * - It is the resource principle — a file read is a second of local work, not a
 *   delegated job.
 * - It is the safety property. Writing goes through a specialist, where berg's
 *   HITL gate makes Sofia decide. If the orchestrator could write directly, the
 *   gate would be bypassed by the one agent that never asks. So `write_file`,
 *   `edit_file` and `run_command` are deliberately NOT given to it.
 *
 * Each is a step, so a replayed turn reads the same thing it read the first time
 * rather than re-reading (or re-running) on every replay.
 */

/** One tool result, as berg's `/api/tool/execute` answers it. */
interface ToolResult {
  output: string;
  status: string;
}

/**
 * Run one read-only workspace tool on berg's Python side.
 *
 * @param tool - The tool name.
 * @param args - Its arguments.
 * @returns The tool's output and status.
 */
async function runWorkspaceTool(
  tool: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  const result = (await callBackend("/api/tool/execute", {
    method: "POST",
    body: JSON.stringify({ tool, args })})) as Partial<ToolResult>;
  return {
    output: String(result.output ?? ""),
    status: String(result.status ?? "ok")};
}

/**
 * Read a file from the workspace.
 *
 * @param filePath - Path relative to the workspace root.
 * @returns The file's contents, or berg's error message.
 */
export async function readWorkspaceFile(filePath: string): Promise<ToolResult> {
  "use step";
  return runWorkspaceTool("read_file", { file_path: filePath });
}

/**
 * List a workspace directory.
 *
 * @param directory - Path relative to the workspace root; the root when absent.
 * @returns The directory's entries, or berg's error message.
 */
export async function listWorkspaceFiles(
  directory?: string,
): Promise<ToolResult> {
  "use step";
  return runWorkspaceTool("list_directory", { file_path: directory ?? "." });
}

/**
 * Search file contents under the workspace.
 *
 * @param pattern - The text to look for.
 * @param directory - Where to look; the whole workspace when absent.
 * @returns The matching lines, or berg's error message.
 */
export async function searchWorkspaceCode(
  pattern: string,
  directory?: string,
): Promise<ToolResult> {
  "use step";
  return runWorkspaceTool("grep", {
    pattern,
    ...(directory ? { directory } : {})});
}
