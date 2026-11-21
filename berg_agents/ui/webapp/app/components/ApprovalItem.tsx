import type { PendingApproval } from "@/harness";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/**
 * One paused tool call inside an approval batch. Each item gets its
 * own `approve` / `reject` / `edit` controls so the user can approve one,
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
    <div className="flex flex-col gap-1.5 rounded-md border border-border p-2">
      <div className="flex items-center gap-2 font-mono text-sm">
        <span>🔧 {approval.toolName}</span>
        {approval.decided ? (
          <Badge variant={approval.reason ? "destructive" : "secondary"}>
            {approval.reason ? "❌ Rejected" : "✅ Approved"}
          </Badge>
        ) : (
          <Badge variant="outline">⏳ Pending</Badge>
        )}
      </div>

      {approval.reason && (
        <div className="text-xs text-muted-foreground">
          Reason: {approval.reason}
        </div>
      )}

      {editing ? (
        <>
          <Textarea
            aria-label={`Edit arguments for ${approval.toolName}`}
            className="min-h-20 w-full bg-muted/50 font-mono text-xs"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              isDisabled={isStreaming}
              size="sm"
              variant="default"
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
            <pre className="overflow-x-auto rounded bg-muted/50 p-2 font-mono text-xs whitespace-pre-wrap">
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
            <div className="flex flex-wrap gap-2">
              <Button
                isDisabled={isStreaming}
                size="sm"
                variant="secondary"
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
