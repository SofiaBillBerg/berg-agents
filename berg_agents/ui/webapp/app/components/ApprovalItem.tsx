import type { PendingApproval } from "@/harness";

import { useState } from "react";
import { Button } from "@heroui/react";

/**
 * One paused tool call inside an approval batch. Each item gets its
 * own approve / reject / edit controls so the user can approve one,
 * reject another, and edit the next. Decided items stay visible with
 * a badge + undo until the batch resumes.
 *
 * Extracted from App.tsx so the same card can be reused by any
 * approval surface (chat batch today; orchestrator gate later).
 */
export function ApprovalItem({
  approval,
  isStreaming,
  onApprove,
  onReject,
  onEdit,
  onRevert}: {
  approval: PendingApproval;
  isStreaming: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEdit: (id: string, args: unknown) => void;
  onRevert: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(approval.args);

  const saveEdit = () => {
    let parsed: unknown = draft;
    try {
      parsed = JSON.parse(draft);
    } catch {
      // Not JSON - pass the raw text through as the edited args.
    }
    onEdit(approval.id, parsed);
    setEditing(false);
  };

  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-border p-1.5">
      <div className="font-mono text-sm">
        🔧 {approval.toolName}{" "}
        {approval.decided ? (
          <span className="text-xs">
            {approval.reason ? "❌ Rejected" : "✅ Approved"}
          </span>
        ) : (
          <span className="text-xs">⏳ Pending</span>
        )}
      </div>
      {approval.reason && (
        <div className="text-xs text-muted-foreground">
          Reason: {approval.reason}
        </div>
      )}
      {editing ? (
        <>
          <textarea
            aria-label={`Edit arguments for ${approval.toolName}`}
            className="font-mono bg-surface-soft p-2 rounded text-xs w-full min-h-20"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              isDisabled={isStreaming}
              size="sm"
              variant="primary"
              onPress={saveEdit}
            >
              💾 Save args
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onPress={() => {
                setDraft(approval.args);
                setEditing(false);
              }}
            >
              Cancel
            </Button>
          </div>
        </>
      ) : (
        <>
          {approval.args && (
            <pre className="font-mono bg-surface-soft p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">
              {approval.args}
            </pre>
          )}
          {approval.decided ? (
            <div className="flex gap-2">
              <Button
                isDisabled={isStreaming}
                size="sm"
                variant="secondary"
                onPress={() => onRevert(approval.id)}
              >
                ↩️ Undo decision
              </Button>
            </div>
          ) : (
            <div className="flex gap-2 flex-wrap">
              <Button
                isDisabled={isStreaming}
                size="sm"
                variant="primary"
                onPress={() => onApprove(approval.id)}
              >
                ✅ Approve
              </Button>
              <Button
                isDisabled={isStreaming}
                size="sm"
                variant="secondary"
                onPress={() => onReject(approval.id)}
              >
                ❌ Reject
              </Button>
              <Button
                isDisabled={isStreaming}
                size="sm"
                variant="secondary"
                onPress={() => setEditing(true)}
              >
                ✏️ Edit args
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default ApprovalItem;
