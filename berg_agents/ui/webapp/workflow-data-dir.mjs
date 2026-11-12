/**
 * Point the Workflow runtime at berg's own durable store.
 *
 * The Workflow plugin defaults `WORKFLOW_LOCAL_DATA_DIR` to
 * `.next/workflow-data` *inside the webapp* when the variable is unset. That
 * default was silently in effect: the TS orchestrator's runs accumulated in
 * `berg_agents/ui/webapp/.next/workflow-data` (40M of them) while every Python
 * specialist run went to `.berg-agents/workflow-data` — two durable stores for
 * one system, with the orchestrator's runs not where the machinery that
 * recovers them looks.
 *
 * Since the plugin only applies its default when the variable is UNSET, setting
 * it here redirects every run to berg's directory. Evaluated before
 * `workflow/next` is imported (see the dynamic import in next.config.mjs),
 * because ES module imports are otherwise hoisted and evaluated first.
 *
 * The precedence mirrors `berg_agents/config/paths.py:resolve_config_dir` so
 * the TS and Python sides agree on where berg's data lives:
 *   1) `BERG_AGENTS_CONFIG_DIR` override, else
 *   2) the checkout's `.berg-agents`.
 */

import {fileURLToPath} from "node:url";

/**
 * Berg's workflow data directory, wherever the config dir resolves.
 *
 * @returns Absolute path of the workflow data directory.
 */
function workflowDataDir() {
  // `BERG_AGENTS_CONFIG_DIR` is the documented override, honoured by Python's
  // `resolve_config_dir`; matching it keeps one location under an override.
  const override = process.env.BERG_AGENTS_CONFIG_DIR;
  if (override) {
    return `${override.replace(/\/+$/, "")}/workflow-data`;
  }
  // No override: the checkout's `.berg-agents`. This module sits at
  // <root>/berg_agents/ui/webapp/, so the repo root is three levels up.
  const root = fileURLToPath(new URL("../../..", import.meta.url));
  return `${root.replace(/\/+$/, "")}/.berg-agents/workflow-data`;
}

process.env.WORKFLOW_LOCAL_DATA_DIR = workflowDataDir();

// Set BOTH variables: the Workflow plugin's guard is on
// `WORKFLOW_TARGET_WORLD`, not on the data dir — it overwrites
// `WORKFLOW_LOCAL_DATA_DIR` with `.next/workflow-data` whenever the target
// world is unset, which is why setting the data dir alone did not take effect.
// Declaring the target world as `local` makes the plugin leave the data dir
// above alone (verified: with only the data dir set, the plugin still
// overwrote it back to `.next/workflow-data`).
if (!process.env.WORKFLOW_TARGET_WORLD) {
  process.env.WORKFLOW_TARGET_WORLD = "local";
}

/**
 * Which world the orchestrator's durability runs on.
 *
 * `local` writes one FILE PER STREAMED PART — measured on 2026-11-12: 8,124
 * chunk files for 28 orchestrator runs, ~123 bytes each, because
 * `@workflow/world-local`'s `streams.write()` lands a file per chunk with no
 * batching and no retention. `WORKFLOW_STREAM_FLUSH_INTERVAL_MS` did not help
 * (tested: 854 files for one turn, WORSE than the 162 without it).
 *
 * So berg runs a real database-backed world instead, and PostgreSQL is the
 * target: it is one durable store, queryable, and swept by ordinary SQL rather
 * than by pruning a directory tree.
 *
 * The database is BERG'S OWN, created by berg's tooling on its own port — not
 * hindsight's, not the system postgres, and not shared with anything else.
 * Coupling berg's durability to another service's database would make that
 * service's migrations a berg outage. The connection string is overridable so
 * an existing deployment can point elsewhere.
 */
if (!process.env.WORKFLOW_TARGET_WORLD || process.env.WORKFLOW_TARGET_WORLD === "local") {
  process.env.WORKFLOW_TARGET_WORLD = "@workflow/world-postgres";
  process.env.WORKFLOW_POSTGRES_URL =
    process.env.WORKFLOW_POSTGRES_URL ||
    process.env.DATABASE_URL ||
    "postgres://world:world@localhost:5434/world";
}
