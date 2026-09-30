import React, { useEffect, useRef } from "react";
import { Button, TextArea } from "@heroui/react";

/**
 * Props for the InputBar component. Prop names and semantics are frozen —
 * `App.tsx` passes all of these and must not change.
 */
export interface InputBarProps {
  /** Current input text (controlled by the parent view). */
  input: string;
  /** Parent state setter for the input text. */
  setInput: (value: React.SetStateAction<string>) => void;
  /** Send handler — slash commands are handled locally, else a harness task. */
  onSend: () => void;
  /** True while a task runs or an approval is pending (blocks new sends). */
  disabled: boolean;
  /** Stop handler — cancels an in-flight streaming request. */
  onStop?: () => void;
  /** Key handler from the parent (Enter-to-send, Escape closes pickers). */
  onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  /** Placeholder shown when the input is empty. */
  placeholder?: string;
}

/**
 * InputBar component — HeroUI v3 rebuild.
 *
 * Chat input field with send button. Disabled while streaming or HITL
 * pending. Auto-resizes based on content (adaptive height between 60px
 * and 300px). The HeroUI TextArea renders a native textarea, so the
 * auto-resize effect keeps working through its forwarded ref.
 */
function InputBar({
  input,
  setInput,
  onSend,
  disabled,
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
  }, [input, disabled]);

  return (
    <div className="input-bar">
      <TextArea
        ref={textareaRef}
        fullWidth
        id="message-input"
        name="message"
        aria-label="Message input"
        className="flex-1 overflow-hidden resize-none"
        disabled={disabled}
        placeholder={placeholder}
        rows={3}
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <Button
        className="min-h-11 shrink-0"
        isDisabled={disabled || !input.trim()}
        variant="primary"
        onPress={onSend}
      >
        {disabled ? "Sending..." : "Send"}
      </Button>

      {disabled && onStop && (
        <Button
          className="min-h-11 shrink-0 border border-warning text-warning hover:bg-warning/10"
          variant="outline"
          onPress={onStop}
        >
          ⏹ Stop
        </Button>
      )}
    </div>
  );
}

export default InputBar;
