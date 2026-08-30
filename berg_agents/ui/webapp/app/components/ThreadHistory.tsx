import React from "react";

/**
 * ThreadHistory component
 * Displays thread history with message count and first words
 */
function ThreadHistory({history}) {
    if (!history || history.length === 0) return null;

    const maxMessages = 10;
    const paginate = (start, end) => history.slice(start, end);

    return (
        <div style={{marginTop: "0.75rem"}}>
            <div style={{fontSize: "0.85rem", color: "#666", marginBottom: "0.5rem"}}>
                Thread History
            </div>
            {history.slice(0, maxMessages).map((msg, idx) => (
                    <div key={idx} style={{fontSize: "0.85rem", color: "#666", marginBottom: "0.3rem"}}>
                        {msg.content}
                    </div>
                )
            )}
            {history.length > maxMessages && (
                <div style={{fontSize: "0.85rem", color: "#666", marginBottom: "0.3rem"}}>
                    ... and {history.length - maxMessages} more
                </div>
            )}
        </div>
    );
}

export default ThreadHistory;
