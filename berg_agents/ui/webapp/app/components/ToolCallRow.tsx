import React from "react";

// Input keys checked (in order) when deriving a chip's human-readable target.
const TARGET_KEYS = [
    "file_path",
    "path",
    "pattern",
    "query",
    "command",
    "directory",
    "url",
];

/**
 * Extract a short human-readable "target" from a tool input payload - e.g.
 * the file_path of read_file or the pattern of glob - so chips and the live
 * activity line show WHAT the agent is touching, not just the tool name.
 *
 * @param {object} input Raw tool input/args object.
 * @returns {string} Display target string, or "" when none is found.
 */
export function toolTarget(input) {
    if (!input || typeof input !== "object") return "";
    for (const key of TARGET_KEYS) {
        const value = input[key];
        if (typeof value === "string" && value.trim()) {
            // Strip the virtual-workspace prefix for readability.
            return value.trim().replace(/^\/workspace\/?/, "");
        }
    }
    return "";
}

/**
 * ToolCallRow component
 * Shows tool execution progress: spinner on start, elapsed time + output on end
 * Collapsible display for tool output
 * Renders all three states: running, finished, error
 * Compatible with @langchain/react AssembledToolCall shape
 */
function ToolCallRow({toolCall}) {
    const [expanded, setExpanded] = React.useState(false);
    const [elapsed, setElapsed] = React.useState(0);

    // Map useStream status to legacy labels
    const status = toolCall.status === "finished" ? "done" : toolCall.status === "error" ? "error" : toolCall.status;

    // Track elapsed time from tool_start
    React.useEffect(() => {
        if (status === "pending" || status === "running") {
            setElapsed(0);
            const startTime = Date.now();
            const interval = setInterval(() => {
                setElapsed((Date.now() - startTime) / 1000);
            }, 100);
            return () => clearInterval(interval);
        }
    }, [status, toolCall.callId]);

    // Update elapsed time when tool ends with specific duration
    React.useEffect(() => {
        if ((status === "done" || status === "finished") && toolCall.elapsedS !== undefined) {
            setElapsed(toolCall.elapsedS);
        }
    }, [status, toolCall.elapsedS, toolCall.callId]);

    const toolName = toolCall.name || toolCall.tool || "Unknown tool";
    const toolInput = toolCall.input ?? toolCall.args ?? {};
    const toolOutput = toolCall.output ?? toolCall.result ?? "";
    const toolError = toolCall.error ?? "";

    const truncatedOutput =
        toolOutput && typeof toolOutput === "string" && toolOutput.length > 200
            ? toolOutput.substring(0, 200) + "…"
            : toolOutput;

    return (
        <div className="tool-call">
            <button
                onClick={() => setExpanded(!expanded)}
                className="tool-call-header"
            >
                <span className="tool-call-name">
                    {(status === "pending" || status === "running") && (
                        <span className="spinner" style={{marginRight: "0.5rem"}}>
                            ⟳
                        </span>
                    )}
                    {toolName}
                    {/* Show WHAT is being acted on (file path / pattern). */}
                    {toolTarget(toolInput) && (
                        <span style={{color: "#888", fontWeight: 400, marginLeft: "0.5rem"}}>
                            {toolTarget(toolInput)}
                        </span>
                    )}
                </span>
                <span className="tool-call-meta">
                    {status === "done" || status === "finished"
                        ? `${elapsed.toFixed(1)}s`
                        : (status === "pending" || status === "running")
                            ? `${elapsed.toFixed(1)}s...`
                            : ""}
                </span>
            </button>
            {expanded && (status === "done" || status === "finished") && (
                <div className="tool-call-body">
                    <div className="tool-call-input">
                        {JSON.stringify(toolInput, null, 2)}
                    </div>
                    <div className="tool-call-output">
                        Output: {truncatedOutput}
                    </div>
                    {toolOutput && typeof toolOutput === "string" && toolOutput.length > 200 && (
                        <details>
                            <summary className="tool-call-summary">
                                Show full output
                            </summary>
                            <div className="tool-call-full-output">
                                {toolOutput}
                            </div>
                        </details>
                    )}
                </div>
            )}
            {expanded && status === "error" && (
                <div className="tool-call-error">
                    Error: {toolError || "Unknown error"}
                </div>
            )}
        </div>
    );
}

export default ToolCallRow;
