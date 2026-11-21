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
 * along with this program.  If not, see <https://gnu.org>.
 */
"use client";

import type { FailureNotice } from "@/harness";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogTitle} from "@/components/ui/dialog";

export function FailureDialog({
  failure,
  onDismiss,
  onRetry}: {
  failure: FailureNotice | null;
  onDismiss: () => void;
  /** Retry the last user text (shown for send-kind failures only). */
  onRetry?: () => void;
}) {
  const copyDetail = () => {
    if (!failure) return;
    try {
      void navigator.clipboard?.writeText(failure.detail);
    } catch {
      // Clipboard unavailable (permissions/private mode) - the text is
      // still on screen and the Details panel keeps a persistent copy.
    }
  };

  return (
    <DialogOverlay
      isOpen={failure != null}
      onOpenChange={(open) => {
        if (!open) onDismiss();
      }}
    >
      <Dialog aria-label="Failure details">
        <DialogHeader>
          <DialogTitle
            className={
              failure?.kind === "recovery" ? "" : "text-(--berg-status-error)"
            }
          >
            {failure?.kind === "recovery" ? "🛠 " : "❌ "}
            {failure?.kind === "run"
              ? "This turn failed"
              : failure?.kind === "recovery"
                ? "Recovered automatically"
                : "Send failed"}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          <p className="text-sm whitespace-pre-wrap">{failure?.detail}</p>
          {failure?.hint && (
            <p className="text-sm text-muted-foreground">{failure.hint}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="secondary" onPress={copyDetail}>
            Copy error
          </Button>
          {failure?.kind === "send" && onRetry && (
            <Button variant="secondary" onPress={onRetry}>
              ↻ Retry last
            </Button>
          )}
          <Button onPress={onDismiss}>Got it</Button>
        </DialogFooter>
      </Dialog>
    </DialogOverlay>
  );
}

export default FailureDialog;
