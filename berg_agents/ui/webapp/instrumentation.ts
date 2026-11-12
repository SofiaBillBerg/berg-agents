/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
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

/**
 * Start the durability world when the server boots.
 *
 * The PostgreSQL world runs a background worker that pulls jobs off
 * graphile-worker, so it has to be started once at boot or runs are enqueued
 * and nothing ever claims them — the orchestrator would appear to start and
 * then go silent. This hook is the documented place for that.
 *
 * Scoped to the node runtime (`NEXT_RUNTIME !== "edge"`), because the runtime
 * it starts is node-only.
 *
 * @see https://nextjs.org/docs/app/guides/instrumentation
 */
export async function register(): Promise<void> {
    if (process.env.NEXT_RUNTIME !== "edge") {
        const {getWorld} = await import("workflow/runtime");
        const world = await getWorld();
        // Optional on worlds that have no worker (the Vercel world does
        // nothing here), so it is safe to call unconditionally.
        await world.start?.();
    }
}
