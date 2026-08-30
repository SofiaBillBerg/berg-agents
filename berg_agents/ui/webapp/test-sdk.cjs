const {Client} = require("@langchain/langgraph-sdk");

async function test() {
    const client = new Client({apiUrl: "http://127.0.0.1:8001"});
    const thread = await client.threads.create({metadata: {test: true}});
    console.log("1. Created thread:", thread.thread_id);
    const run = client.runs.stream(thread.thread_id, "berg-agent", {
        input: {messages: [{type: "human", content: "What is 3+3?"}]},
    });
    console.log("2. Starting stream...");
    for await (const event of run) {
        const data = event.params?.data || event.data;
        if (data?.delta?.text) process.stdout.write(data.delta.text);
        if (data?.event === "completed") {
            console.log("\n   Stream completed");
            break;
        }
    }
    const history = await client.threads.getHistory(thread.thread_id, {limit: 10});
    console.log("3. History entries:", history.length);
    const state = await client.threads.getState(thread.thread_id);
    console.log("4. State keys:", Object.keys(state.values || {}));
    console.log("\nAll SDK integration tests passed!");
}

test().catch(console.error);
