import React, {useRef, useEffect} from "react";

/**
 * InputBar component
 * Chat input field with send button
 * Disabled while streaming or HITL pending
 * Auto-resizes based on content (adaptive height)
 */
function InputBar({input, setInput, onSend, disabled, onKeyDown, placeholder = "Type a message..."}) {
    const textareaRef = useRef(null);

    // Auto-resize textarea based on content
    useEffect(() => {
        const textarea = textareaRef.current;
        if (!textarea) return;
        
        // Reset height to auto to get the correct scrollHeight
        textarea.style.height = 'auto';
        // Set height to scrollHeight, with min and max bounds
        const minHeight = 60;
        const maxHeight = 300;
        const newHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
        textarea.style.height = `${newHeight}px`;
    }, [input, disabled]);

    return (
        <div className="input-bar">
            <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={placeholder}
                disabled={disabled}
                className="input-bar-textarea"
                style={{overflow: 'hidden', resize: 'none', background: 'var(--berg-surface)', color: 'var(--berg-text)'}}
            />
            <button
                onClick={onSend}
                disabled={disabled || !input.trim()}
                className="input-bar-button"
            >
                {disabled ? "Sending..." : "Send"}
            </button>
        </div>
    );
}

export default InputBar;
