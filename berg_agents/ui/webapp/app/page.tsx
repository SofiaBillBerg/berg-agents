/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
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
 * Main landing page for the Berg Agents web application.
 * Imports theme assets and renders the interactive client application.
 *
 * NOTE: do NOT add `export const dynamic = "force-dynamic"` here - the
 * project builds with `output: "export"` (static, mounted by FastAPI),
 * which requires every page to be statically prerenderable. The
 * `ClientOnly` wrapper below defers `useChat` (which uses `Math.random()`
 * internally) until after mount, so prerendering only ever sees the
 * deterministic "Loading chat..." fallback.
 */

import { Suspense } from "react";
// Import KaTeX styles for math rendering
import "katex/dist/katex.min.css";

import { ClientOnly } from "./client.tsx";

/**
 * Root Page component for Next.js App Router.
 *
 * @returns JSX element rendering the client-only application.
 */
export default function Page() {
  return (
    <Suspense fallback={<div className="p-8 text-sm">Loading chat...</div>}>
      <ClientOnly />
    </Suspense>
  );
}
