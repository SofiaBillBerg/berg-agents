/*
 * <one line to give the program's name and a brief idea of what it does.>
 *
 * Copyright (c) 2026.
 *         Copyright (C) <year>  <name of author>
 *
 *         This program is free software: you can redistribute it and/or modify
 *         it under the terms of the GNU Affero General Public License as
 *         published by the Free Software Foundation, either version 3 of the
 *         License, or (at your option) any later version.
 *
 *         This program is distributed in the hope that it will be useful,
 *         but WITHOUT ANY WARRANTY; without even the implied warranty of
 *         MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *         GNU Affero General Public License for more details.
 *
 *         You should have received a copy of the GNU Affero General Public License
 *         along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 */

import React, { useEffect, useRef } from "react";
import { Button, TextArea } from "@heroui/react";

/**
 * Props for the InputBar component. Prop names and semantics are frozen -
 * `App.tsx` passes all of these and must not change.
 */
export interface InputBarProps {
  /** Current input text (controlled by the parent view). */
  input: string;
  /** Parent state setter for the input text. */
  setInput: (value: React.SetStateAction<string>) => void;
  /** Send handler - slash commands are handled locally, else a harness task. */
  onSend: () => void;
  /** True while a response streams (send then interrupts + redirects). */
  streaming: boolean;
  /** Stop handler - cancels an in-flight streaming request. */
  onStop?: () => void;
  /** Key handler from the parent (Enter-to-send, Escape closes pickers). */
  onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  /** Placeholder shown when the input is empty. */
  placeholder?: string;
}

/**
 * InputBar component - HeroUI v3 rebuild.
 *
 * Chat input field with send button. The box stays editable while
 * streaming so the user can steer: pressing Send mid-stream stops the
 * current response and sends the new message instead (interrupt and
 * redirect). ⏹ Stop cancels outright. Auto-resizes based on content
 * (adaptive height between 60px and 300px). The HeroUI TextArea
 * renders a native textarea, so the auto-resize effect keeps working
 * through its forwarded ref.
 */
function InputBar({
  input,
  setInput,
  onSend,
  streaming,
  onStop,
  onKeyDown,
  placeholder = "Type a message..."}: InputBarProps) {
  // Ref to the underlying native textarea (forwarded by HeroUI TextArea).
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea based on content.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // Reset height to auto to get the correct scrollHeight.
    textarea.style.height = "auto";
    // Set height to scrollHeight, with min and max bounds.
    const minHeight = 60;
    const maxHeight = 300;
    const newHeight = Math.min(
      Math.max(textarea.scrollHeight, minHeight),
      maxHeight,
    );
    textarea.style.height = `${newHeight}px`;
  }, [input, streaming]);

  return (
    <div className="input-bar">
      <TextArea
        ref={textareaRef}
        fullWidth
        aria-label="Message input"
        className="flex-1 overflow-hidden resize-none"
        id="message-input"
        name="message"
        placeholder={
          streaming ? "Type to interrupt and redirect…" : placeholder
        }
        rows={3}
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <span
        title={
          streaming
            ? "Stop the current response and send this instead"
            : "Send message"
        }
      >
        <Button
          className="min-h-11 shrink-0"
          isDisabled={!input.trim()}
          variant="primary"
          onPress={onSend}
        >
          {streaming ? "↩ Send" : "Send"}
        </Button>
      </span>

      {streaming && onStop && (
        <span title="Cancel the in-flight response">
          <Button
            className="min-h-11 shrink-0 border border-warning text-warning hover:bg-warning/10"
            variant="outline"
            onPress={onStop}
          >
            ⏹ Stop
          </Button>
        </span>
      )}
    </div>
  );
}

export default InputBar;
