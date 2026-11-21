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

import React, { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

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
 * InputBar component.
 *
 * Chat input field with send button. The box stays editable while
 * streaming so the user can steer: pressing Send mid-stream stops the
 * current response and sends the new message instead (interrupt and
 * redirect). ⏹ Stop cancels outright. Auto-resizes based on content
 * (adaptive height between 60px and 300px).
 */
function InputBar({
  input,
  setInput,
  onSend,
  streaming,
  onStop,
  onKeyDown,
  placeholder = "Type a message..."}: InputBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea based on content.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = "auto";
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
      <Textarea
        ref={textareaRef}
        aria-label="Message input"
        className="w-full flex-1 resize-none overflow-hidden"
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
          variant="default"
          onPress={onSend}
        >
          {streaming ? "↩ Send" : "Send"}
        </Button>
      </span>

      {streaming && onStop && (
        <span title="Cancel the in-flight response">
          <Button
            className="min-h-11 shrink-0 border border-amber-500/60 text-amber-600 hover:bg-amber-500/10"
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
