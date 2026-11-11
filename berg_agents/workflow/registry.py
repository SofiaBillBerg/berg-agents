"""berg's own durable workflow runtime.

Three pieces, and this module is the one that ties them together:

* :mod:`berg_agents.workflow.queue` — the broker that owns the messages, so
  work survives the process dying (proven: a run killed mid-step completed after
  a restart, once its lease expired).
* :mod:`berg_agents.workflow.routes` — the two HTTP surfaces the SDK needs:
  the queue's intake, and the consumer the SDK hands back.
* this module — the registry that declares berg's workflows, and the worker
  that dispatches.

Two coupling rules, both found by running the runtime and recorded in
``decisions/decisions-log.md`` (2026-11-10/11):

1. the registry is built with ``as_vercel_job=False``. Constructing it the
   default way makes it build and subscribe the queue entrypoint *itself*; berg
   mounts that consumer itself, and a second subscription raises
   ``DuplicateSubscriptionError`` on ``__wkf_workflow_*``.
2. the consumer is handed the **bare payload**. The SDK's entrypoint re-wraps
   the ``{payload, queueName, deploymentId}`` envelope itself, so sending the
   stored envelope double-wraps it and the run dies on a
   ``WorkflowInvokePayload`` validation error.

Everything runs locally: the runtime's world falls back to its on-disk local
world unless ``VERCEL_DEPLOYMENT_ID`` is set, and nothing here needs Vercel.
"""

from __future__ import annotations

import asyncio
import os

import pydantic
from vercel import workflow


def _workflow_data_dir() -> os.PathLike[str]:
    """Berg's own home for the runtime's event log, steps, hooks and streams."""
    from berg_agents.config.paths import resolve_config_dir

    path = resolve_config_dir(None) / "workflow-data"
    path.mkdir(parents=True, exist_ok=True)
    return path


# berg keeps its own stores under its config dir (``sessions.db``,
# ``runs.db`` and now this). The workflow runtime's local world otherwise
# defaults to ``.workflow-data`` in the process's cwd, which for berg would be
# wherever the server happened to be started from. Set before the world is
# first constructed — the runtime builds it lazily, and berg's consumer route
# is what first asks for it.
os.environ.setdefault("WORKFLOW_LOCAL_DATA_DIR", str(_workflow_data_dir()))


#: How long the worker sleeps when the queue is empty. berg's broker is polled
#: rather than pushed, so this is the trade between latency and an idle core.
_IDLE_POLL_SECONDS = 0.5

#: One registry per namespace. Two registries in one process both subscribe to
#: ``__wkf_workflow_*`` and the second raises DuplicateSubscriptionError, so
#: berg keeps exactly one.
wf = workflow.Workflows(as_vercel_job=False)


class Chunk(pydantic.BaseModel):
    """One transcript chunk on a run's namespaced durable stream.

    The shape the AI SDK already consumes, so a run's work renders in berg's
    existing chat surface without a second protocol.
    """

    kind: str
    text: str


# ------------------------------------------------------------------- the worker
async def _dispatch_loop() -> None:
    """Claim, deliver, settle — forever. berg's worker.

    Imported lazily so that importing this module (at server start, from
    ``routes.py``) never pulls the SDK's HTTP path in with it. An idle queue
    sleeps rather than spins: a worker with no backoff is a busy loop that
    costs a core for nothing.
    """
    import asyncio

    from berg_agents.workflow.routes import receive_delivery

    while True:
        if await receive_delivery() == 0:
            await asyncio.sleep(_IDLE_POLL_SECONDS)


def start_worker() -> asyncio.Task:
    """Start berg's queue worker as a task on the running loop.

    Called from ``create_app``'s lifespan, beside the run-registry sweeper, so
    both of the process's background loops start and stop together.

    :return: The worker's task, so the lifespan can cancel it on shutdown.
    """
    return asyncio.create_task(_dispatch_loop(), name="workflow.queue-worker")


__all__ = ["Chunk", "start_worker", "wf"]
