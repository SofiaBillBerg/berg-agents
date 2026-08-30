import { useEffect } from "react";
import { useStream } from "@langchain/react";

import { API_BASE } from "../envConfig.ts";

function MinimalStream() {
  const stream = useStream({
    assistantId: "berg_agents",
    apiUrl: API_BASE,
  });

  useEffect(() => {
    console.log("[MinimalStream] stream ready", {
      threadId: stream.threadId,
      isLoading: stream.isLoading,
      error: stream.error,
      subagentsType: stream.subagents?.constructor?.name,
      subagentsSize: stream.subagents?.size,
      valuesKeys: stream.values ? Object.keys(stream.values) : [],
    });
  }, [
    stream.threadId,
    stream.isLoading,
    stream.error,
    stream.subagents,
    stream.values,
  ]);

  const handleSubmit = async () => {
    console.log("[MinimalStream] submitting...");
    try {
      await stream.submit({
        messages: [{ type: "human", content: "hello" }],
      });
      console.log("[MinimalStream] submit complete");
    } catch (e) {
      console.error("[MinimalStream] submit error", e);
    }
  };

  return (
    <div style={{ padding: "2rem", fontFamily: "monospace" }}>
      <h1>Minimal Stream Test</h1>
      <p>Thread ID: {stream.threadId || "none"}</p>
      <p>Loading: {stream.isLoading ? "yes" : "no"}</p>
      <p>Error: {stream.error ? String(stream.error) : "none"}</p>
      <p>Messages: {stream.messages?.length || 0}</p>
      <p>Tool calls: {stream.toolCalls?.length || 0}</p>
      <p>Subagents: {stream.subagents?.size || 0}</p>
      <button onClick={handleSubmit}>Send hello</button>
    </div>
  );
}

export default MinimalStream;
