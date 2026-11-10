"""berg's first workflow: one agent turn, durable and streamable.

This is the host's proof, not the chat agent. It exists so the queue, the
consumer, the typed stream and the model step are all exercised inside berg's
own server — which is what phase 1b swaps ``LiveRun`` against in 1c. When that
happens this module becomes the first real turn workflow; until then it is
deliberately small, and it is labelled as the temporary path.

The model is berg's own: ``resolve_model_instance`` is the same function every
other agent in this codebase calls, pointed at the local base URL berg's
configuration declares.
"""

from __future__ import annotations

from typing import Any

from berg_agents.workflow.registry import Chunk, wf
from vercel import workflow


@wf.step
async def emit(*, writable: Any, kind: str, text: str) -> None:
    """Publish one transcript chunk. Only a step may touch a stream."""
    await writable.write(Chunk(kind=kind, text=text))


@wf.step(cancellable=True)
async def model_turn(*, prompt: str, instructions: str | None = None) -> str:
    """One model call on berg's local model, as a durable step.

    A step is what makes the turn survivable: it replays from its recorded
    result when the worker dies, and it dies cleanly when the run is terminated.
    """
    from berg_agents.providers.models import resolve_model_instance
    from pydantic_ai import Agent

    agent = Agent(
        resolve_model_instance(None),
        instructions=instructions
        or "You are a terse coding assistant. Answer in one short sentence.",
    )
    result = await agent.run(prompt)
    return str(result.output)


@wf.workflow
async def turn(*, token: str, prompt: str) -> dict:
    """One durable, streamable turn.

    :param token: Namespace for this turn's hooks and streams.
    :param prompt: The user's message.
    :return: The turn's outcome, readable from a fresh ``Run`` handle.
    """
    stream = workflow.get_writable(type=Chunk, namespace=token)
    await emit(writable=stream, kind="start", text=prompt[:200])
    answer = await model_turn(prompt=prompt)
    await emit(writable=stream, kind="answer", text=answer)
    # Closing is a step's job too: a workflow body may not touch the stream.
    from berg_agents.workflow.turn import _close

    await _close(writable=stream)
    return {"answer": answer}


@wf.step
async def _close(*, writable: Any) -> None:
    """Close the stream so readers know the turn is over."""
    await writable.close()
