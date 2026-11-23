/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *
 * You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * Which model an empty orchestrator choice actually runs on.
 *
 * The picker's "default" option used to be labelled with the first model of the
 * first tier, while an empty choice resolves through berg's configured
 * `defaultModel` — a different model. So the control named one thing and did
 * another, which is how a person came to believe they had selected a model the
 * run never used.
 *
 * This answers with the truth, and with the truth ONLY: the model id. The
 * resolver it asks carries an `api_key` for endpoints that need one, and that
 * key must not reach a browser — so this route asks on the server's behalf and
 * returns the single field the UI has any business knowing. Anything more than
 * that belongs behind the seam, not in the page.
 */

import { backendOrigin } from "@/harness/specialists";

/**
 * GET /api/orchestrator/default-model
 *
 * @returns `{model}` — the id an empty choice resolves to.
 */
export async function GET(): Promise<Response> {
  try {
    const response = await fetch(`${backendOrigin()}/api/providers/resolve`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const resolved = (await response.json()) as { model?: string };
    return Response.json({ model: resolved.model ?? "" });
  } catch {
    // No answer is better than a wrong one: the picker then omits the model
    // from its label rather than naming a model it cannot promise.
    return Response.json({ model: "" });
  }
}
