import React, {useEffect, useState, useMemo} from "react";

/**
 * HitlSurface component — Human-in-the-loop approval card.
 *
 * Renders the agent's pending interrupt as one or more "action requests"
 * (tool name + JSON args) and emits a LangChain HITL *decision* through
 * `onDecision`, using the schema understood by langchain's
 * HumanInTheLoopMiddleware resume path:
 *
 *   - approve: {"type": "approve"}
 *   - reject:  {"type": "reject", "message": "..."}
 *   - edit:    {"type": "edit", "edited_action": {"name": ..., "args": ...}}
 *
 * When several actions were interrupted in parallel, a decision *array* is
 * emitted so each action gets exactly one entry (order-aligned).
 */

/**
 * Human-readable descriptions for known tools.
 * Maps tool name -> { description, icon, category }
 */
const TOOL_DESCRIPTIONS = {
    // File operations
    read_file: {description: "Read the contents of a file", icon: "📄", category: "File"},
    write_file: {description: "Create or overwrite a file", icon: "📝", category: "File"},
    edit_file: {description: "Make targeted edits to a file", icon: "✏️", category: "File"},
    list_files: {description: "List files in a directory", icon: "📁", category: "File"},
    glob_files: {description: "Find files matching a pattern", icon: "🔍", category: "File"},
    delete_file: {description: "Delete a file", icon: "🗑️", category: "File", dangerous: true},
    
    // Shell/Command operations
    run_command: {description: "Execute a shell command", icon: "💻", category: "Shell", dangerous: true},
    run_in_terminal: {description: "Run a command in the terminal", icon: "⌨️", category: "Shell"},
    
    // Code operations
    search_code: {description: "Search code for a pattern", icon: "🔎", category: "Code"},
    find_symbol: {description: "Find a symbol definition", icon: "🎯", category: "Code"},
    get_definition: {description: "Get definition of a symbol", icon: "📖", category: "Code"},
    get_references: {description: "Find references to a symbol", icon: "🔗", category: "Code"},
    
    // Web operations
    web_search: {description: "Search the web", icon: "🌐", category: "Web"},
    web_fetch: {description: "Fetch content from a URL", icon: "📥", category: "Web"},
    
    // Git operations
    git_status: {description: "Show git status", icon: "📊", category: "Git"},
    git_diff: {description: "Show git diff", icon: "📝", category: "Git"},
    git_commit: {description: "Create a git commit", icon: "✅", category: "Git"},
    git_push: {description: "Push to remote", icon: "🚀", category: "Git"},
    git_pull: {description: "Pull from remote", icon: "⬇️", category: "Git"},
    
    // Task/Planning
    create_task: {description: "Create a todo task", icon: "📋", category: "Planning"},
    update_task: {description: "Update a todo task", icon: "✏️", category: "Planning"},
    
    // MCP tools (common patterns)
    mcp_: {description: "MCP server tool", icon: "🔌", category: "MCP"},
};

/**
 * Get tool description with fallback logic
 */
function getToolInfo(name) {
    // Exact match
    if (TOOL_DESCRIPTIONS[name]) {
        return TOOL_DESCRIPTIONS[name];
    }
    // Prefix match for MCP tools
    for (const [prefix, info] of Object.entries(TOOL_DESCRIPTIONS)) {
        if (prefix.endsWith('_') && name.startsWith(prefix)) {
            return {...info, description: `${info.description}: ${name.replace(prefix, '')}`};
        }
    }
    // Fallback
    return {description: "Run a tool", icon: "🔧", category: "Tool"};
}

/**
 * Normalize any supported interrupt payload into a flat list of actions.
 *
 * Supported shapes:
 *   - protocol v2 value:  {action_requests: [{action|name, args}], review_configs?}
 *   - array of interrupts: [{value: {action_requests: [...]}}]
 *   - legacy surface prop: {tool: string, input: object}
 *
 * @param {object|string} pending - Structured interrupt from useCustomStream
 *   ({id, value}) or a plain string message (no editable args).
 * @returns {Array<{name: string, args: object}>}
 */
function extractActions(pending) {
    if (!pending || typeof pending !== "object") return [];
    
    // The interrupt value can be in various shapes depending on the source
    let value = pending.value;
    
    // If value is an Interrupt object (has .value attribute), unwrap it
    if (value && typeof value === "object" && "value" in value && "id" in value) {
        value = value.value;
    }
    
    // Collect raw action entries from every known container shape.
    let raw = [];
    if (value && Array.isArray(value.action_requests)) {
        raw = value.action_requests;
    } else if (Array.isArray(value)) {
        // Multiple simultaneous interrupts (parallel branches): flatten them.
        raw = value.flatMap((item) => {
            if (item?.value?.action_requests) return item.value.action_requests;
            if (item?.action_requests) return item.action_requests;
            if (item?.value && typeof item.value === "object") return [item.value];
            return [];
        });
    } else if (value?.action_requests) {
        raw = value.action_requests;
    } else if (value && typeof value === "object") {
        // Single action or unknown shape - treat the whole value as one action
        raw = [value];
    } else if (pending.tool) {
        // Legacy surface prop shape: {tool, input}
        raw = [{name: pending.tool, args: pending.input}];
    }

    // Normalize each entry to {name, args}
    return raw.map((entry) => ({
        name: entry.action || entry.name || entry.tool || "unknown",
        args: entry.args || entry.input || entry.parameters || entry.value || {},
    }));
}

/**
 * Format args object as readable summary (not full JSON)
 */
function formatArgsSummary(args) {
    if (!args || typeof args !== "object") return "";
    const keys = Object.keys(args);
    if (keys.length === 0) return "no arguments";
    
    // Show first 3 keys with truncated values
    const shown = keys.slice(0, 3).map(k => {
        const v = args[k];
        const str = typeof v === "string" ? v : JSON.stringify(v);
        return `${k}: ${str.length > 50 ? str.slice(0, 47) + "..." : str}`;
    });
    const more = keys.length > 3 ? ` +${keys.length - 3} more` : "";
    return shown.join(", ") + more;
}

function HitlSurface({pending, toolCalls = [], subagents = null, onDecision}) {
    const [showEdit, setShowEdit] = useState(false);
    const [editedArgs, setEditedArgs] = useState("");
    const [editError, setEditError] = useState(null);
    const [elapsed, setElapsed] = useState(0);

    const actions = useMemo(() => extractActions(pending), [pending]);

    // Track elapsed time while HITL is pending (reset whenever it clears).
    useEffect(() => {
        if (!pending) {
            setElapsed(0);
            return;
        }
        const startTime = Date.now();
        const interval = setInterval(() => {
            setElapsed((Date.now() - startTime) / 1000);
        }, 1000);
        return () => clearInterval(interval);
    }, [pending]);

    // Pre-fill the edit textarea with the first action's current args (or raw value if no actions).
    useEffect(() => {
        if (actions.length > 0) {
            try {
                setEditedArgs(JSON.stringify(actions[0].args, null, 2));
            } catch {
                setEditedArgs(String(actions[0].args));
            }
        } else if (pending?.value != null) {
            try {
                const v = pending.value;
                setEditedArgs(typeof v === "string" ? v : JSON.stringify(v, null, 2));
            } catch {
                setEditedArgs(String(pending.value));
            }
        } else {
            setEditedArgs("");
        }
        setShowEdit(false);
        setEditError(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pending]);

    if (!pending) return null;

    /** Continue without changes → approve every action. */
    const handleContinue = () => {
        onDecision(
            actions.length > 1
                ? actions.map(() => ({type: "approve"}))
                : {type: "approve"},
        );
    };

    /** Reject every action with a short human-readable reason. */
    const handleReject = () => {
        const decision = {type: "reject", message: "Rejected by user"};
        onDecision(
            actions.length > 1
                ? actions.map(() => ({...decision}))
                : decision,
        );
    };

    /**
     * Submit edited args for the FIRST action; remaining actions (if any)
     * continue unchanged so the decisions array stays order-aligned.
     * If no structured actions were parsed, treat edit as approve with a message
     * (so the user can still proceed via Edit).
     */
    const handleEditSubmit = () => {
        if (actions.length === 0) {
            // No structured actions — try to parse as JSON, fall back to approve with text
            try {
                const parsed = JSON.parse(editedArgs);
                onDecision({type: "edit", edited_action: {name: "unknown", args: parsed}});
            } catch {
                // If not valid JSON, treat as plain approve (user edited raw text)
                onDecision({type: "approve"});
            }
            return;
        }
        try {
            const parsedArgs = JSON.parse(editedArgs);
            const first = actions[0];
            const editDecision = {
                type: "edit",
                edited_action: {name: first.name, args: parsedArgs},
            };
            onDecision(
                actions.length > 1
                    ? [editDecision, ...actions.slice(1).map(() => ({type: "approve"}))]
                    : editDecision,
            );
        } catch (err) {
            setEditError(`Invalid JSON: ${err.message}`);
        }
    };

    return (
        <div
            style={{
                margin: "var(--berg-sp-4) 0",
                padding: "var(--berg-sp-4)",
                background: "var(--berg-status-warn, #fff8e1)",
                border: "2px solid var(--berg-status-warn, #ffca28)",
                borderRadius: "var(--berg-radius)",
                display: "flex",
                flexDirection: "column",
                gap: "var(--berg-sp-3)",
            }}
        >
            <div
                style={{
                    fontSize: "var(--berg-fs-sm)",
                    fontWeight: "600",
                    color: "var(--berg-status-warn, #e65100)",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                }}
            >
                <span>Awaiting your approval</span>
                <span style={{fontSize: "var(--berg-fs-xs)", color: "var(--berg-status-warn, #e65100)"}}>
          Waiting: {elapsed.toFixed(1)}s
        </span>
            </div>

            {/* Render every pending action (tool name + args). */}
            {actions.map((action, idx) => {
                const toolInfo = getToolInfo(action.name);
                const isDangerous = toolInfo.dangerous;
                const argsSummary = formatArgsSummary(action.args);
                
                return (
                    <div key={idx} style={{
                        display: "flex", 
                        flexDirection: "column", 
                        gap: "0.4rem",
                        padding: "0.75rem",
                        background: isDangerous ? "rgba(215, 48, 39, 0.08)" : "var(--berg-surface)",
                        border: `1px solid ${isDangerous ? "rgba(215, 48, 39, 0.3)" : "var(--berg-border)"}`,
                        borderRadius: "var(--berg-radius)",
                        borderLeft: `4px solid ${isDangerous ? "var(--berg-status-error)" : toolInfo.category === "File" ? "var(--berg-brand-purple)" : toolInfo.category === "Shell" ? "var(--berg-status-warn)" : toolInfo.category === "Web" ? "var(--berg-status-info)" : "var(--berg-status-success)"}`,
                    }}>
                        <div style={{display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap"}}>
                            <span style={{fontSize: "1.2rem"}}>{toolInfo.icon}</span>
                            <span style={{fontWeight: "600", color: "var(--berg-brand-blue)", fontFamily: "var(--berg-font-mono)"}}>
                                {action.name}
                            </span>
                            <span style={{
                                fontSize: "var(--berg-fs-xs)",
                                fontWeight: "600",
                                padding: "0.1rem 0.4rem",
                                borderRadius: "var(--berg-radius-sm)",
                                background: toolInfo.category === "File" ? "rgba(125, 2, 156, 0.12)" :
                                           toolInfo.category === "Shell" ? "rgba(253, 159, 7, 0.12)" :
                                           toolInfo.category === "Web" ? "rgba(59, 82, 139, 0.12)" :
                                           toolInfo.category === "Git" ? "rgba(33, 144, 140, 0.12)" :
                                           toolInfo.category === "Planning" ? "rgba(232, 65, 199, 0.12)" :
                                           toolInfo.category === "MCP" ? "rgba(134, 3, 166, 0.12)" : "var(--berg-border)",
                                color: toolInfo.category === "File" ? "var(--berg-brand-purple)" :
                                       toolInfo.category === "Shell" ? "var(--berg-status-warn)" :
                                       toolInfo.category === "Web" ? "var(--berg-status-info)" :
                                       toolInfo.category === "Git" ? "var(--berg-status-success)" :
                                       toolInfo.category === "Planning" ? "var(--berg-accent-orchid)" :
                                       toolInfo.category === "MCP" ? "var(--berg-accent-magenta)" : "var(--berg-muted)",
                                textTransform: "uppercase",
                                letterSpacing: "0.05em",
                            }}>
                                {toolInfo.category}
                            </span>
                            {isDangerous && (
                                <span style={{
                                    fontSize: "var(--berg-fs-xs)",
                                    fontWeight: "600",
                                    padding: "0.1rem 0.4rem",
                                    borderRadius: "var(--berg-radius-sm)",
                                    background: "rgba(215, 48, 39, 0.12)",
                                    color: "var(--berg-status-error)",
                                    textTransform: "uppercase",
                                }}>
                                    ⚠️ Potentially destructive
                                </span>
                            )}
                            {actions.length > 1 && showEdit && idx === 0 && (
                                <span style={{marginLeft: "0.5rem", fontSize: "var(--berg-fs-xs)", color: "var(--berg-muted)"}}>
                                    (editing applies to this action)
                                </span>
                            )}
                        </div>
                        <div style={{fontSize: "var(--berg-fs-sm)", color: "var(--berg-text)", lineHeight: 1.5}}>
                            <span style={{fontWeight: "500", color: "var(--berg-muted)"}}>What it does: </span>
                            <span>{toolInfo.description}</span>
                        </div>
                        <div style={{fontSize: "var(--berg-fs-sm)", color: "var(--berg-muted)"}}>
                            <span style={{fontWeight: "500"}}>Arguments: </span>
                            <code style={{fontFamily: "var(--berg-font-mono)", fontSize: "var(--berg-fs-xs)", background: "var(--berg-code-bg)", padding: "0.1rem 0.3rem", borderRadius: "var(--berg-radius-sm)"}}>
                                {argsSummary}
                            </code>
                        </div>
                        <details style={{marginTop: "0.25rem"}}>
                            <summary style={{
                                cursor: "pointer",
                                fontSize: "var(--berg-fs-xs)",
                                color: "var(--berg-muted)",
                                fontWeight: "500",
                            }}>
                                Show full JSON arguments
                            </summary>
                            <pre style={{
                                margin: "0.5rem 0 0",
                                padding: "0.75rem",
                                background: "var(--berg-surface-tint)",
                                border: "1px solid var(--berg-border)",
                                borderRadius: "var(--berg-radius)",
                                fontFamily: "var(--berg-font-mono)",
                                fontSize: "var(--berg-fs-xs)",
                                whiteSpace: "pre-wrap",
                                wordBreak: "break-word",
                                maxHeight: "200px",
                                overflowY: "auto",
                            }}>
{JSON.stringify(action.args, null, 2)}
      </pre>
                        </details>
                    </div>
                );
            })}

            {/* Fallback when the payload carried no parseable actions — show last tool call as context. */}
            {actions.length === 0 && (() => {
                const rawValue = pending.value;
                const isString = typeof rawValue === "string";
                const displayText = isString ? rawValue : (rawValue?.message || rawValue?.description || "");
                const hasDisplay = displayText && displayText !== "Approval required" && displayText !== "Input required";
                // Try to surface the last tool call that likely triggered the interrupt
                const lastTool = toolCalls && toolCalls.length ? toolCalls[toolCalls.length - 1] : null;
                const subagentList = subagents ? Array.from(subagents instanceof Map ? subagents.values() : subagents) : [];
                const lastSubagentTool = subagentList.length ? subagentList.flatMap(s => s.toolCalls || []).slice(-1)[0] : null;
                const relevantTool = lastTool || lastSubagentTool;
                return (
                    <div style={{padding: "var(--berg-sp-3)", background: "var(--berg-surface)", borderRadius: "var(--berg-radius)", border: "1px solid var(--berg-border)", display: "flex", flexDirection: "column", gap: "var(--berg-sp-2)"}}>
                        {relevantTool && (
                            <div style={{padding: "0.5rem", background: "rgba(125, 2, 156, 0.06)", border: "1px solid var(--berg-border)", borderRadius: "var(--berg-radius)", display: "flex", flexDirection: "column", gap: "0.3rem"}}>
                                <div style={{fontSize: "var(--berg-fs-xs)", color: "var(--berg-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em"}}>Last tool activity (likely awaiting approval)</div>
                                <div style={{display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap"}}>
                                    <span style={{fontFamily: "var(--berg-font-mono)", fontWeight: 600, color: "var(--berg-brand-blue)"}}>{relevantTool.name}</span>
                                    <code style={{fontSize: "var(--berg-fs-xs)", background: "var(--berg-code-bg)", padding: "0.1rem 0.3rem", borderRadius: "var(--berg-radius-sm)"}}>{formatArgsSummary(relevantTool.input || relevantTool.args)}</code>
                                </div>
                                <details>
                                    <summary style={{cursor: "pointer", fontSize: "var(--berg-fs-xs)", color: "var(--berg-muted)"}}>Show full args</summary>
                                    <pre style={{margin: "0.4rem 0 0", padding: "0.5rem", background: "var(--berg-surface-tint)", borderRadius: "var(--berg-radius-sm)", fontSize: "var(--berg-fs-xs)", whiteSpace: "pre-wrap"}}>{JSON.stringify(relevantTool.input || relevantTool.args || {}, null, 2)}</pre>
                                </details>
                            </div>
                        )}
                        {isString && rawValue ? (
                            <div style={{fontSize: "var(--berg-fs-sm)", color: "var(--berg-text)", lineHeight: 1.5}}>
                                <span style={{fontWeight: 600}}>Agent says:</span>{" "}
                                <span style={{whiteSpace: "pre-wrap"}}>{rawValue}</span>
                            </div>
                        ) : hasDisplay ? (
                            <div style={{fontSize: "var(--berg-fs-sm)", color: "var(--berg-text)"}}>{displayText}</div>
                        ) : !relevantTool && (
                            <span style={{color: "var(--berg-muted)"}}>Agent is waiting for your decision — no action details were provided.</span>
                        )}
                        <span style={{fontSize: "var(--berg-fs-xs)", color: "var(--berg-muted)"}}>
                            The backend did not send structured action details. Latest tool call shown above (if any) is the likely action awaiting <b>Approve / Reject / Edit</b>.
                        </span>
                        <details style={{marginTop: "var(--berg-sp-1)"}}>
                            <summary style={{cursor: "pointer", fontSize: "var(--berg-fs-xs)", color: "var(--berg-muted)"}}>
                                Show raw interrupt data
                            </summary>
                            <pre style={{
                                margin: "0.5rem 0 0",
                                padding: "0.5rem",
                                background: "var(--berg-surface-tint)",
                                borderRadius: "var(--berg-radius-sm)",
                                fontSize: "var(--berg-fs-xs)",
                                overflow: "auto",
                                maxHeight: "150px",
                                whiteSpace: "pre-wrap",
                                wordBreak: "break-word",
                            }}>
{typeof rawValue === "string" ? rawValue : JSON.stringify(rawValue, null, 2)}
                            </pre>
                        </details>
                    </div>
                );
            })()}

            {showEdit && actions.length > 0 && (
                <div style={{display: "flex", flexDirection: "column", gap: "var(--berg-sp-2)"}}>
          <textarea
              value={editedArgs}
              onChange={(e) => {
                  setEditedArgs(e.target.value);
                  setEditError(null);
              }}
              style={{
                  width: "100%",
                  padding: "0.5rem",
                  borderRadius: "var(--berg-radius)",
                  border: "1px solid var(--berg-border)",
                  fontFamily: "var(--berg-font-mono)",
                  fontSize: "var(--berg-fs-sm)",
                  resize: "vertical",
                  minHeight: "100px",
                  background: "var(--berg-surface)",
                  color: "var(--berg-text)",
              }}
              placeholder="Edit JSON args here"
          />
                    {editError && (
                        <div
                            style={{
                                padding: "0.5rem",
                                background: "rgba(215, 48, 39, 0.12)",
                                border: "1px solid var(--berg-status-error)",
                                borderRadius: "var(--berg-radius)",
                                color: "var(--berg-status-error)",
                                fontSize: "var(--berg-fs-sm)",
                            }}
                        >
                            {editError}
                        </div>
                    )}
                </div>
            )}

            <div style={{display: "flex", gap: "var(--berg-sp-2)", marginTop: "var(--berg-sp-3)", flexWrap: "wrap"}}>
                <button
                    onClick={() => {
                        if (showEdit) {
                            handleEditSubmit();
                        } else {
                            handleContinue();
                        }
                    }}
                    style={{
                        flex: 1,
                        minWidth: "110px",
                        padding: "0.6rem 1rem",
                        border: "none",
                        borderRadius: "var(--berg-radius)",
                        background: showEdit ? "var(--berg-brand-blue)" : "var(--berg-status-success)",
                        color: "#fff",
                        fontSize: "var(--berg-fs-sm)",
                        cursor: "pointer",
                        fontWeight: "600",
                    }}
                    title={showEdit ? "Save edited arguments and approve" : "Approve all pending actions"}
                >
                    {showEdit ? "Save & Approve" : "✓ Approve"}
                </button>
                <button
                    onClick={handleReject}
                    style={{
                        flex: 1,
                        minWidth: "110px",
                        padding: "0.6rem 1rem",
                        border: "none",
                        borderRadius: "var(--berg-radius)",
                        background: "var(--berg-status-error)",
                        color: "#fff",
                        fontSize: "var(--berg-fs-sm)",
                        cursor: "pointer",
                        fontWeight: "600",
                    }}
                    title="Reject all pending actions"
                >
                    ✕ Reject
                </button>
                <button
                    onClick={() => {
                        setShowEdit(!showEdit);
                        setEditError(null);
                    }}
                    style={{
                        padding: "0.6rem 1rem",
                        border: "1px solid var(--berg-border)",
                        borderRadius: "var(--berg-radius)",
                        background: showEdit ? "var(--berg-surface-tint)" : "transparent",
                        color: showEdit ? "var(--berg-text)" : "var(--berg-muted)",
                        fontSize: "var(--berg-fs-sm)",
                        cursor: "pointer",
                        fontWeight: "500",
                    }}
                    title={actions.length > 0 ? "Edit arguments before approving (only first action)" : "Edit raw data as JSON (no structured actions detected)"}
                >
                    {showEdit ? "Cancel Edit" : "✎ Edit"}
                </button>
            </div>
        </div>
    );
}

export default HitlSurface;