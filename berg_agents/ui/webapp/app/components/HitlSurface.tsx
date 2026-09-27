import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Chip, TextArea } from "@heroui/react";

/** Decision type emitted by the HITL surface to the backend.
 * Matches `schemas.py HitlDecision` exactly: `decision` field only.
 */
export type HitlDecision =
  | { decision: "approve" }
  | { decision: "reject"; message?: string }
  | {
      decision: "edit";
      edited_action: { name: string; args: Record<string, unknown> };
    };

/** Props for the HitlSurface component. */
export interface HitlSurfaceProps {
  /** The pending interrupt payload from the harness hook. */
  pending: Record<string, unknown> | null;
  /** Tool calls from the current run (used for fallback context display). */
  toolCalls?: Array<{
    callId: string;
    name: string;
    input: unknown;
    status: string;
  }>;
  /** Active subagents map (used for fallback context display). */
  subagents?: Map<string, { toolCalls?: unknown[] }> | null;
  /** Callback to deliver the user's approval/rejection/edit decision. */
  onDecision: (decision: HitlDecision | HitlDecision[]) => void;
}

/**
 * HitlSurface component — Human-in-the-loop approval card.
 *
 * Renders the agent's pending interrupt as one or more "action requests"
 * (tool name + JSON args) and emits a LangChain HITL *decision* through
 * `onDecision`
 *
 * - approve: {"type": "approve"}
 * - reject: {"type": "reject", "message": "..."}
 * - edit: {"type": "edit", "edited_action": {"name": ..., "args": ...}}
 *
 * When several actions were interrupted in parallel, a decision *array* is
 * emitted so each action gets exactly one entry (order-aligned).
 */

/** Static metadata for a tool: human description, category, danger flag. */
interface ToolInfo {
  description: string;
  category: string;
  dangerous?: boolean;
}

/**
 * Human-readable descriptions for known tools.
 * Maps tool name -> { description, category }.
 */
const TOOL_DESCRIPTIONS: Record<string, ToolInfo> = {
  // File operations
  read_file: { description: "Read the contents of a file", category: "File" },
  write_file: { description: "Create or overwrite a file", category: "File" },
  edit_file: { description: "Make targeted edits to a file", category: "File" },
  list_files: { description: "List files in a directory", category: "File" },
  glob_files: {
    description: "Find files matching a pattern",
    category: "File",
  },
  delete_file: {
    description: "Delete a file",
    category: "File",
    dangerous: true,
  },

  // Shell/Command operations
  run_command: {
    description: "Execute a shell command",
    category: "Shell",
    dangerous: true,
  },
  run_in_terminal: {
    description: "Run a command in the terminal",
    category: "Shell",
  },

  // Code operations
  search_code: { description: "Search code for a pattern", category: "Code" },
  find_symbol: { description: "Find a symbol definition", category: "Code" },
  get_definition: {
    description: "Get definition of a symbol",
    category: "Code",
  },
  get_references: {
    description: "Find references to a symbol",
    category: "Code",
  },

  // Web operations
  web_search: { description: "Search the web", category: "Web" },
  web_fetch: { description: "Fetch content from a URL", category: "Web" },

  // Git operations
  git_status: { description: "Show git status", category: "Git" },
  git_diff: { description: "Show git diff", category: "Git" },
  git_commit: { description: "Create a git commit", category: "Git" },
  git_push: { description: "Push to remote", category: "Git" },
  git_pull: { description: "Pull from remote", category: "Git" },

  // Task/Planning
  create_task: { description: "Create a todo task", category: "Planning" },
  update_task: { description: "Update a todo task", category: "Planning" },

  // MCP tools (common patterns)
  mcp_: { description: "MCP server tool", category: "MCP" },
};

/**
 * Get tool description with fallback logic.
 *
 * @param name - Tool name (always a string in practice)
 */
function getToolInfo(name: string): ToolInfo {
  // Exact match
  if (TOOL_DESCRIPTIONS[name]) {
    return TOOL_DESCRIPTIONS[name];
  }
  // Prefix match for MCP tools
  for (const [prefix, info] of Object.entries(TOOL_DESCRIPTIONS)) {
    if (prefix.endsWith("_") && name.startsWith(prefix)) {
      return {
        ...info,
        description: `${info.description}: ${name.replace(prefix, "")}`,
      };
    }
  }
  // Fallback
  return { description: "Run a tool", category: "Tool" };
}

/**
 * Chip color for a tool category. Semantic colors only — no raw values.
 */
function categoryColor(
  category: string,
): "default" | "accent" | "success" | "warning" | "danger" {
  switch (category) {
    case "Shell":
      return "warning";
    case "Git":
      return "success";
    case "File":
    case "Web":
    case "MCP":
      return "accent";
    default:
      return "default";
  }
}

/**
 * Normalize any supported interrupt payload into a flat list of actions.
 *
 * Supported shapes:
 * - protocol v2 value: {action_requests: [{action|name, args}], review_configs?}
 * - array of interrupts: [{value: {action_requests: [...]}}]
 * - legacy surface prop: {tool: string, input: object}
 * - flat guardian review (what the backend actually sends today):
 *   {status: "needs_human_review", review_reasons|reasons, risk_level,
 *   complexity, ...} — carries no tool actions, so it yields zero actions
 *   and the review summary below renders instead.
 *
 * @param pending - Structured interrupt from useHarness
 * (`orch.hitlRequest`: {id, value}) or a plain string message (no editable
 * args).
 * @returns Array of normalized {name, args} actions.
 */

function extractActions(
  pending: any,
): Array<{ name: string; args: Record<string, unknown> }> {
  if (!pending || typeof pending !== "object") return [];

  // The interrupt value can be in various shapes depending on the source

  // Support both: {value: {action_requests: [...]} } (legacy) and
  // flat API format: {status, review_reasons, action_requests: [...]} (current)
  let value: any = pending.value;

  // Flat payloads carry the fields at the top level (no .value wrapper).
  if (value === undefined) value = pending;

  // If value is an Interrupt object (has .value attribute), unwrap it
  if (value && typeof value === "object" && "value" in value && "id" in value) {
    value = value.value;
  }

  // A guardian review verdict is not a tool action — never treat its
  // reason/risk fields as an action's args. Only apply this when there
  // are no explicit action_requests at the top level.
  if (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    !(pending as any)?.action_requests &&
    !Array.isArray((value as any).action_requests) &&
    ((value as any).status === "needs_human_review" ||
      Array.isArray((value as any).review_reasons) ||
      Array.isArray((value as any).reasons))
  ) {
    return [];
  }

  // Collect raw action entries from every known container shape.
  // Support both .value wrapper and top-level API format (e.g. {status, review_reasons, action_requests}).
  let raw: any[] = [];
  if (value && Array.isArray((value as any).action_requests)) {
    raw = (value as any).action_requests;
  } else if (pending && Array.isArray((pending as any).action_requests)) {
    raw = (pending as any).action_requests;
  } else if (Array.isArray(value)) {
    // Multiple simultaneous interrupts (parallel branches): flatten them.
    raw = value.flatMap((item: any) => {
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
  } else if ((pending as any).tool) {
    // Legacy surface prop shape: {tool, input}
    raw = [{ name: (pending as any).tool, args: (pending as any).input }];
  }

  // Normalize each entry to {name, args}
  return raw.map((entry: any) => ({
    name: entry.action || entry.name || entry.tool || "unknown",
    args: entry.args || entry.input || entry.parameters || entry.value || {},
  }));
}

/** Guardian review verdict, as the backend actually sends it today. */
export interface ReviewSummary {
  reasons: string[];
  riskLevel: string | null;
  complexity: string | null;
  confidence: number | null;
  description: string | null;
  taskType: string | null;
  taskId: string | null;
}

/**
 * Pull the guardian's review verdict out of a HITL payload.
 *
 * Handles both shapes the backend emits:
 * - sync POST /api/harness: {status: "needs_human_review", task_id,
 *   task_type, complexity, risk_level, review_reasons[], confidence}
 * - stream `hitl-requested` event: {reasons[], risk_level, complexity}
 * (plus `description`, stitched on by the hook in both cases).
 *
 * Returns null when the payload carries no review fields.
 */
function extractReview(pending: any): ReviewSummary | null {
  if (!pending || typeof pending !== "object") return null;
  // Support both {value} wrapper and flat API format (top-level review_reasons etc.)
  const src: any =
    pending.value && typeof pending.value === "object"
      ? pending.value
      : pending;
  const reasons = Array.isArray(src.review_reasons)
    ? src.review_reasons
    : Array.isArray(src.reasons)
      ? src.reasons
      : [];
  const riskLevel = typeof src.risk_level === "string" ? src.risk_level : null;
  const complexity = typeof src.complexity === "string" ? src.complexity : null;
  const confidence = typeof src.confidence === "number" ? src.confidence : null;
  const description =
    typeof src.description === "string" && src.description
      ? src.description
      : null;
  const taskType = typeof src.task_type === "string" ? src.task_type : null;
  const taskId =
    typeof src.task_id === "string"
      ? src.task_id
      : typeof src.thread_id === "string"
        ? src.thread_id
        : null;
  if (
    reasons.length === 0 &&
    !riskLevel &&
    !complexity &&
    !description &&
    src.status !== "needs_human_review"
  ) {
    return null;
  }
  return {
    reasons: reasons.map(String),
    riskLevel,
    complexity,
    confidence,
    description,
    taskType,
    taskId,
  };
}

/**
 * Chip color for a guardian risk level. Semantic colors only.
 */
function riskColor(
  level: string | null,
): "default" | "accent" | "success" | "warning" | "danger" {
  switch ((level ?? "").toLowerCase()) {
    case "critical":
      return "danger";
    case "high":
      return "warning";
    case "medium":
      return "accent";
    case "low":
      return "success";
    default:
      return "default";
  }
}

/**
 * Format args object as readable summary (not full JSON)
 */
function formatArgsSummary(args: Record<string, unknown>) {
  if (!args || typeof args !== "object") return "";
  const keys = Object.keys(args);
  if (keys.length === 0) return "no arguments";

  // Show first 3 keys with truncated values
  const shown = keys.slice(0, 3).map((k) => {
    const v = args[k];
    const str = typeof v === "string" ? v : JSON.stringify(v);
    return `${k}: ${str.length > 50 ? str.slice(0, 47) + "..." : str}`;
  });
  const more = keys.length > 3 ? ` +${keys.length - 3} more` : "";
  return shown.join(", ") + more;
}

/**
 * Format the pre-fill text for the edit textarea: the first action's args,
 * else the raw interrupt value, else empty. Pure helper so the component can
 * derive this state during render (see HitlSurface below).
 */
function formatEditPrefill(
  pending: Record<string, unknown> | null,
  actions: Array<{ name: string; args: Record<string, unknown> }>,
): string {
  if (actions.length > 0) {
    const action = actions[0];
    const targetPath =
      action.args?.path ?? action.args?.virtual_path ?? action.args?.filename;

    // Build a clear, actionable edit instruction that explains what will be modified
    const verb =
      action.name === "write_file"
        ? "Create or overwrite"
        : action.name === "edit_file"
          ? "Edit this file"
          : action.name === "delete_file"
            ? "Delete this file"
            : "Execute this action";

    if (targetPath && typeof targetPath === "string") {
      // If it's a file action, show clear instruction about what will be edited
      if (action.name === "write_file" || action.name === "edit_file") {
        return `// Edit or create: ${targetPath}

// ${verb} the file above with your changes.

// Current file content will be available for editing.
// You can modify, add, or delete content as needed.`;
      }

      // For other actions, show clear instruction
      return `// Target: ${targetPath}

// This action will ${action.name.replace("_", " ")} the above target.

// Make your edits below or provide additional parameters.`;
    }

    // Fallback: show original JSON but with clear instruction prefix
    try {
      const jsonStr = JSON.stringify(action.args, null, 2);
      return `// Edit action parameters below
// 
// Make changes to the JSON above to modify how this action executes.
// Ensure the structure remains valid JSON.

${jsonStr}`;
    } catch {
      return String(action.args);
    }
  }
  // Flat guardian payloads carry no .value wrapper — pre-fill from the
  // whole payload (review reasons) instead of nothing.
  const value = (pending as any)?.value ?? pending;
  if (value != null) {
    try {
      return typeof value === "string" ? value : JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return "";
}

/**
 * Body of a single pending action: tool name, category/danger badges, human
 * description, args summary, and a collapsible full-JSON view. Rendered
 * inside either a bordered block (normal) or a danger Alert (destructive).
 */
function ActionBody({
  action,
  showEditNote,
}: {
  /* patterns-explicit-variants: explicit props (action, showEditNote) instead of boolean mode flags */
  action: { name: string; args: Record<string, unknown> };
  showEditNote: boolean;
}) {
  const toolInfo = getToolInfo(action.name);
  const isDangerous = toolInfo.dangerous === true;
  const argsSummary = formatArgsSummary(action.args);
  // The file path IS the approval decision — surface it boldly, not as
  // small print. Supports the common arg spellings the planner emits.
  const targetPath =
    action.args?.path ??
    action.args?.virtual_path ??
    action.args?.filename ??
    null;
  const verb =
    action.name === "write_file"
      ? "Create or overwrite"
      : action.name === "edit_file"
        ? "Edit"
        : action.name === "delete_file"
          ? "Delete"
          : "Run";

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-foreground px-1.5 py-0.5 text-xs font-bold text-background">
          AGENT WILL EXECUTE
        </span>
        <span className="font-mono font-semibold">{action.name}</span>
        <Chip color={categoryColor(toolInfo.category)} size="sm">
          {toolInfo.category}
        </Chip>
        {isDangerous && (
          <Chip color="danger" size="sm">
            Potentially destructive
          </Chip>
        )}
        {showEditNote && (
          <span className="text-xs text-muted">
            (editing applies to this action)
          </span>
        )}
      </div>
      {typeof targetPath === "string" && targetPath.trim() !== "" ? (
        <p className="text-base leading-relaxed">
          <span className="font-semibold text-foreground">{verb}: </span>
          <code className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-sm font-bold">
            {targetPath}
          </code>
        </p>
      ) : (
        <p className="text-sm leading-relaxed">
          <span className="font-semibold text-foreground">Agent will: </span>
          <span className="font-medium">{toolInfo.description}</span>
        </p>
      )}
      <p className="text-sm text-muted">
        <span className="font-medium">Target / Arguments: </span>
        <code className="rounded border border-border bg-surface px-1 font-mono text-xs">
          {argsSummary}
        </code>
      </p>
      <details>
        <summary className="cursor-pointer text-xs font-medium text-muted">
          Show full JSON arguments
        </summary>
        <pre className="mt-2 max-h-50 overflow-y-auto rounded-lg border border-border bg-surface p-3 font-mono text-xs whitespace-pre-wrap wrap-break-word">
          {JSON.stringify(action.args, null, 2)}
        </pre>
      </details>
    </>
  );
}

function HitlSurface({
  /* architecture-compound-components: compound = Card + ActionBody + ReviewSummary; shared via props. */
  /* architecture-compound-components: compound = Card + ActionBody + ReviewSummary; shared via props, not inline flags */
  pending,
  toolCalls = [],
  subagents = null,
  onDecision,
}: HitlSurfaceProps) {
  const [showEdit, setShowEdit] = useState(false);
  // Prefill the edit textarea with the first action's real args right
  // at mount — the surface only exists while a request is pending, so
  // the initial value must carry it (the render-phase reset below
  // never fires on first mount).
  const [editedArgs, setEditedArgs] = useState(() =>
    formatEditPrefill(pending, extractActions(pending)),
  );
  const [editError, setEditError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const actions = useMemo(() => extractActions(pending), [pending]);
  // Guardian review verdict (flat sync/stream payloads) — rendered as
  // reason bullets + risk/complexity/confidence chips above the fallback.
  const review = useMemo(() => extractReview(pending), [pending]);

  // Reset the elapsed timer whenever a new interrupt arrives (or clears).
  // Adjusted during render instead of in the effect below, to avoid a
  // synchronous setState cascade.
  const [prevPendingForTimer, setPrevPendingForTimer] = useState(pending);
  if (prevPendingForTimer !== pending) {
    setPrevPendingForTimer(pending);
    setElapsed(0);
  }

  // Track elapsed time while HITL is pending (subscription only).
  useEffect(() => {
    if (!pending) return;
    const startTime = Date.now();
    const interval = setInterval(() => {
      setElapsed((Date.now() - startTime) / 1000);
    }, 1000);
    return () => clearInterval(interval);
  }, [pending]);

  // Pre-fill the edit textarea with the first action's current args (or raw
  // value if no actions). Derived during render via formatEditPrefill instead
  // of in an effect, to avoid a synchronous setState cascade.
  const [prevPendingForEdit, setPrevPendingForEdit] = useState(pending);
  if (prevPendingForEdit !== pending) {
    setPrevPendingForEdit(pending);
    setEditedArgs(formatEditPrefill(pending, actions));
    setShowEdit(false);
    setEditError(null);
  }

  if (!pending) return null;

  /** Continue without changes → approve every action. */
  const handleContinue = () => {
    onDecision(
      actions.length > 1
        ? actions.map(() => ({ decision: "approve" }))
        : { decision: "approve" },
    );
  };

  /** Reject every action with a short human-readable reason. */
  const handleReject = () => {
    const decision: HitlDecision = {
      decision: "reject",
      message: "Rejected by user",
    };
    onDecision(
      actions.length > 1 ? actions.map(() => ({ ...decision })) : decision,
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
      try {
        const parsed = JSON.parse(editedArgs);
        onDecision({
          decision: "edit",
          edited_action: { name: "unknown", args: parsed },
        });
      } catch {
        onDecision({ decision: "approve" });
      }
      return;
    }
    try {
      const parsedArgs = JSON.parse(editedArgs);
      const first = actions[0];
      const editDecision: HitlDecision = {
        decision: "edit",
        edited_action: { name: first.name, args: parsedArgs },
      };
      onDecision(
        actions.length > 1
          ? [
              editDecision,
              ...actions.slice(1).map(() => ({ decision: "approve" }) as const),
            ]
          : editDecision,
      );
    } catch (err) {
      setEditError(`Invalid JSON: ${err.message}`);
    }
  };

  return (
    <Card className="my-4">
      <Card.Header>
        <Card.Title>
          {(() => {
            // Show concrete HITL reason from backend (e.g. review_reasons array or reason string)
            const rawPending: any = (pending as any) || {};
            const reviewReasons: string[] =
              rawPending.review_reasons ||
              (rawPending.value as any)?.review_reasons ||
              (rawPending.value?.value as any)?.review_reasons ||
              [];
            if (Array.isArray(reviewReasons) && reviewReasons.length > 0) {
              return reviewReasons.join("; ");
            }
            const concreteReason =
              rawPending.reason ||
              (rawPending.value as any)?.reason ||
              (rawPending.value?.value as any)?.reason;
            if (
              concreteReason &&
              typeof concreteReason === "string" &&
              concreteReason.length > 0
            ) {
              return concreteReason;
            }
            // Fallback: show first action's concrete description
            if (actions.length > 0) {
              const a = actions[0];
              const info = getToolInfo(a.name);
              const argsStr = formatArgsSummary(a.args);
              return `Agent wants to ${info.description.toLowerCase()} (${a.name}) — ${argsStr}`;
            }
            return "Agent wants to execute — approve / reject / edit?";
          })()}
        </Card.Title>
        <Card.Description>Waiting: {elapsed.toFixed(1)}s</Card.Description>
      </Card.Header>
      <Card.Content className="flex flex-col gap-3">
        {/* Render every pending action (tool name + args). */}
        {actions.map(
          (
            action: { name: string; args: Record<string, unknown> },
            idx: number,
          ) => {
            const body = (
              <ActionBody
                action={action}
                showEditNote={actions.length > 1 && showEdit && idx === 0}
              />
            );
            // Destructive tools get a danger Alert wrapper; the rest render
            // in a plain bordered block.
            return getToolInfo(action.name).dangerous === true ? (
              <Alert key={idx} status="danger">
                <Alert.Indicator />
                <Alert.Content>{body}</Alert.Content>
              </Alert>
            ) : (
              <div
                key={idx}
                className="flex flex-col gap-2 rounded-xl border border-border p-3"
              >
                {body}
              </div>
            );
          },
        )}

        {/* Fallback when the payload carried no parseable actions — show the
            guardian review verdict (reasons + chips) or the last tool call
            as context. Handles both wrapped ({value}) and flat payloads. */}
        {actions.length === 0 &&
          (() => {
            // Flat guardian payloads carry fields at the top level; wrapped
            // interrupts nest them under .value.
            const rawValue =
              pending.value !== undefined &&
              pending.value !== null &&
              typeof pending.value === "object"
                ? (pending.value as Record<string, unknown> | string)
                : (pending as Record<string, unknown> | string);
            const isString = typeof rawValue === "string";
            const displayText = isString
              ? rawValue
              : review?.description ||
                (rawValue?.message as string) ||
                (rawValue?.description as string) ||
                "";
            const hasDisplay =
              displayText &&
              displayText !== "Approval required" &&
              displayText !== "Input required";
            // Try to surface the last tool call that likely triggered the interrupt
            const lastTool =
              toolCalls && toolCalls.length
                ? toolCalls[toolCalls.length - 1]
                : null;
            const subagentList = subagents
              ? Array.from(
                  subagents instanceof Map ? subagents.values() : subagents,
                )
              : [];
            const lastSubagentTool = subagentList.length
              ? (subagentList as any[])
                  .flatMap((s: any) => s.toolCalls || [])
                  .slice(-1)[0]
              : null;
            const relevantTool = lastTool || lastSubagentTool;
            return (
              <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3">
                {/* Guardian review verdict: why it asked + risk chips. */}
                {review && (
                  <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3">
                    <div className="text-xs font-semibold tracking-wider text-muted uppercase">
                      Agent / Model Request
                    </div>
                    {review.description && (
                      <p className="text-sm leading-relaxed font-medium">
                        <span className="font-semibold">Task: </span>
                        <span className="whitespace-pre-wrap">
                          {review.description}
                        </span>
                      </p>
                    )}
                    {review.reasons.length > 0 && (
                      <ul className="flex flex-col gap-1 text-sm">
                        {review.reasons.map((reason, i) => (
                          <li key={i} className="flex gap-2">
                            <span aria-hidden="true">•</span>
                            <span>{reason}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {review.riskLevel && (
                        <Chip color={riskColor(review.riskLevel)} size="sm">
                          Risk: {review.riskLevel}
                        </Chip>
                      )}
                      {review.complexity && (
                        <Chip color="default" size="sm">
                          Complexity: {review.complexity}
                        </Chip>
                      )}
                      {review.confidence != null && (
                        <Chip color="default" size="sm">
                          Confidence: {Math.round(review.confidence * 100)}%
                        </Chip>
                      )}
                      {review.taskType && (
                        <Chip color="default" size="sm">
                          {review.taskType}
                        </Chip>
                      )}
                    </div>
                  </div>
                )}
                {relevantTool && (
                  <div className="flex flex-col gap-1 rounded-lg border border-border bg-surface p-2">
                    <div className="text-xs font-semibold tracking-wider text-muted uppercase">
                      Last tool activity (likely awaiting approval)
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono font-semibold">
                        {relevantTool.name}
                      </span>
                      <code className="rounded border border-border bg-surface px-1 font-mono text-xs">
                        {formatArgsSummary(
                          relevantTool.input || relevantTool.args,
                        )}
                      </code>
                    </div>
                    <details>
                      <summary className="cursor-pointer text-xs text-muted">
                        Show full args
                      </summary>
                      <pre className="mt-2 rounded-lg border border-border bg-surface p-2 font-mono text-xs whitespace-pre-wrap">
                        {JSON.stringify(
                          relevantTool.input || relevantTool.args || {},
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </div>
                )}
                {isString && rawValue ? (
                  <p className="text-sm leading-relaxed">
                    <span className="font-semibold">Agent says:</span>{" "}
                    <span className="whitespace-pre-wrap">{rawValue}</span>
                  </p>
                ) : hasDisplay ? (
                  <p className="text-sm">{displayText}</p>
                ) : (
                  !relevantTool &&
                  !review && (
                    <span className="text-muted">
                      Agent is waiting for your decision — no action details
                      were provided.
                    </span>
                  )
                )}
                {/* Only explain the missing structured payload when there is
                    really nothing to show — a guardian review already
                    explains itself. */}
                {!review && (
                  <span className="text-xs text-muted">
                    The backend did not send structured action details. Latest
                    tool call shown above (if any) is the likely action awaiting{" "}
                    <b>Approve / Reject / Edit</b>.
                  </span>
                )}
                <details>
                  <summary className="cursor-pointer text-xs text-muted">
                    Show raw interrupt data
                  </summary>
                  <pre className="mt-2 max-h-37.5 overflow-auto rounded-lg border border-border bg-surface p-2 font-mono text-xs whitespace-pre-wrap wrap-break-word">
                    {typeof rawValue === "string"
                      ? rawValue
                      : JSON.stringify(pending, null, 2)}
                  </pre>
                </details>
              </div>
            );
          })()}

        {showEdit && actions.length > 0 && (
          <div className="flex flex-col gap-2">
            <TextArea
              fullWidth
              aria-label="Edited action arguments (JSON)"
              placeholder="Edit JSON args here"
              rows={5}
              value={editedArgs}
              variant="secondary"
              onChange={(e) => {
                setEditedArgs(e.target.value);
                setEditError(null);
              }}
            />
            {editError && (
              <Alert status="danger">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>{editError}</Alert.Title>
                </Alert.Content>
              </Alert>
            )}
          </div>
        )}
      </Card.Content>
      <Card.Footer className="flex flex-wrap gap-2">
        <Button
          aria-label={
            showEdit
              ? "Save edited arguments and approve"
              : "Approve all pending actions"
          }
          className="min-h-11 min-min-w-27.5x-1"
          onPress={() => {
            if (showEdit) {
              handleEditSubmit();
            } else {
              handleContinue();
            }
          }}
        >
          {showEdit ? "Save & Approve" : "✓ Approve"}
        </Button>
        <Button
          aria-label="Reject all pending actions"
          className="min-h-11 min-min-w-27.5x-1"
          variant="danger"
          onPress={handleReject}
        >
          ✕ Reject
        </Button>
        <Button
          aria-label={
            actions.length > 0
              ? "Edit arguments before approving (only first action)"
              : "Edit raw data as JSON (no structured actions detected)"
          }
          className="min-h-11"
          variant="secondary"
          onPress={() => {
            setShowEdit(!showEdit);
            setEditError(null);
          }}
        >
          {showEdit ? "Cancel Edit" : "✎ Edit"}
        </Button>
      </Card.Footer>
    </Card>
  );
}

export default HitlSurface;
