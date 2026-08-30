import React, {useEffect, useState} from "react";
import {useStream, useMessages, useToolCalls} from "@langchain/react";

function TestStream() {
    const stream = useStream({
        assistantId: "berg_agents",
        apiUrl: "http://localhost:8001",
    });

    const messages = useMessages(stream);
    const toolCalls = useToolCalls(stream);
    const subagents = stream.subagents ? Array.from(stream.subagents.values()) : [];
    const todos = Array.isArray(stream.values?.todos) ? stream.values.todos : [];
    const interrupt = stream.interrupt;
    const isLoading = stream.isLoading;
    const threadId = stream.threadId;
    const error = stream.error;

    useEffect(() => {
        console.log("[TestStream] State update", {
            threadId,
            isLoading,
            error,
            messagesLen: messages?.length,
            toolCallsLen: toolCalls?.length,
            subagentsLen: subagents?.length,
            todosLen: todos?.length,
            interrupt,
            messagesType: messages?.constructor?.name,
            toolCallsType: toolCalls?.constructor?.name,
            subagentsType: stream.subagents?.constructor?.name,
            todosType: stream.values?.todos?.constructor?.name,
        });
    });

    return (
        <div style={{padding: "2rem", fontFamily: "monospace"}}>
            <h1>Test Stream</h1>
            <p>Thread ID: {threadId || "none"}</p>
            <p>Loading: {isLoading ? "yes" : "no"}</p>
            <p>Error: {error ? String(error) : "none"}</p>
            <p>Messages: {messages?.length || 0} (type: {messages?.constructor?.name || "undefined"})</p>
            <p>Tool calls: {toolCalls?.length || 0} (type: {toolCalls?.constructor?.name || "undefined"})</p>
            <p>Subagents: {subagents?.length || 0} (type: {stream.subagents?.constructor?.name || "undefined"})</p>
            <p>Todos: {todos?.length || 0} (type: {stream.values?.todos?.constructor?.name || "undefined"})</p>
            <p>Interrupt: {interrupt ? "yes" : "no"}</p>

            <h2>Messages</h2>
            {Array.isArray(messages) && messages.map((msg, i) => (
                <div key={i} style={{marginBottom: "1rem", padding: "0.5rem", border: "1px solid #ccc"}}>
                    <strong>{msg._getType?.() || msg.type || "unknown"}</strong>
                    <div>{typeof msg.text === "string" ? msg.text : JSON.stringify(msg.text)}</div>
                </div>
            ))}

            <h2>Tool Calls</h2>
            {Array.isArray(toolCalls) && toolCalls.map((tc, i) => (
                <div key={i} style={{marginBottom: "0.5rem"}}>
                    {tc.name || tc.tool} - {tc.status}
                </div>
            ))}
        </div>
    );
}

export default TestStream;
