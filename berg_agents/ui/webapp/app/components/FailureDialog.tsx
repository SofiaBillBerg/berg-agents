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

"use client";

import type { FailureNotice } from "@/harness";

import { Button, Modal } from "@heroui/react";


/**
 * FailureDialog - the ONE surface a failure is read on.
 *
 * Every fatal failure lands here as a {@link FailureNotice}: a send that
 * failed, a run that died, or the system's recovery of one (the old
 * systemNotice alert's content). The dialog is modal and dismiss-when-read
 * (backdrop click, ESC, or the Got it button) - it demands attention once,
 * then gets out of the way. The durable record stays in the transcript:
 * failed runs journal their "❌ This turn failed" text into the history,
 * and the collapsed Details panel keeps the raw client error line.
 *
 * The hint is pre-computed by whoever knows the cause (the server for run
 * failures, a tiny transport rule client-side); this component never
 * diagnoses - it only presents.
 */
export function FailureDialog({
  failure,
  onDismiss,
  onRetry}: {
  failure: FailureNotice | null;
  onDismiss: () => void;
  /** Retry the last user text (shown for send-kind failures only). */
  onRetry?: () => void;
}) {
  // Copy the raw error text so a bug report carries the exact words the
  // run produced - the dialog is dismiss-when-read, the clipboard is not.
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
    <Modal.Backdrop
      isOpen={failure != null}
      onOpenChange={(open) => {
        if (!open) onDismiss();
      }}
    >
      <Modal.Container>
        <Modal.Dialog aria-label="Failure details">
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading
              className={
                failure?.kind === "recovery" ? "" : "text-[var(--berg-status-error)]"
              }
            >
              {failure?.kind === "recovery" ? "🛠 " : "❌ "}
              {failure?.kind === "run"
                ? "This turn failed"
                : failure?.kind === "recovery"
                  ? "Recovered automatically"
                  : "Send failed"}
            </Modal.Heading>
          </Modal.Header>
          <Modal.Body>
            <p className="text-sm whitespace-pre-wrap">{failure?.detail}</p>
            {failure?.hint && (
              <p className="text-sm text-muted-foreground">{failure.hint}</p>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onPress={copyDetail}>
              Copy error
            </Button>
            {failure?.kind === "send" && onRetry && (
              <Button variant="secondary" onPress={onRetry}>
                ↻ Retry last
              </Button>
            )}
            <Button slot="close" onPress={onDismiss}>
              Got it
            </Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}

export default FailureDialog;
