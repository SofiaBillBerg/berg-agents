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

/** @type {import('next').NextConfig} */

// `withWorkflow` enables the "use workflow" and "use step" directives, which is
// what lets the orchestrator run as a durable agent inside this app.

// It MUST be imported AFTER ./workflow-data-dir.mjs, because that module sets
// `WORKFLOW_LOCAL_DATA_DIR` and the Workflow plugin only applies its own default
// (`.next/workflow-data`, inside the webapp) when the variable is UNSET. A
// static `import` of withWorkflow above the assignment would be evaluated
// first — ES module imports are hoisted — and the plugin's default would win,
// which is exactly the bug this fixes. The dynamic import makes the order
// explicit rather than relying on hoisting rules.
await import("./workflow-data-dir.mjs");

const {withWorkflow} = await import("workflow/next");

// Bundle analyzer for Phase 2 performance monitoring
// Enable with: ANALYZE=true bun run build
const withBundleAnalyzer =
  process.env.ANALYZE === "true"
    ? (await import("@next/bundle-analyzer")).default({
        enabled: process.env.ANALYZE === "true",
        compression: false})
    : (config) => config;

const nextConfig = {
  // A real Next server, not a static export. The orchestrator is a
  // `WorkflowAgent`, and the Workflow runtime starts and resumes runs from
  // server routes — which a static export cannot host. The comment this
  // replaces said the opposite ("static export only in production, FastAPI
  // mounts dist/"), which was true while the UI had no server behaviour of its
  // own; it does now.
  //
  // ONE FRONT DOOR. The UI is served by Next now, but berg's API, sessions,
  // specialists and workflow routes all live in the Python backend. Rather than
  // make the user (or the browser) juggle two origins, Next proxies everything
  // under /api/* that it does not handle itself through to Python.
  //
  // The split is by ownership, and it is deliberately narrow: a Next route file
  // that exists (today only `app/api/orchestrator`) wins, because Next matches
  // filesystem routes BEFORE rewrites. Everything else under /api/* is Python's.
  // That is why `/api/orchestrator` must never be added to the exclusion list
  // below — it would make the orchestrator unreachable.
  //
  // `BERG_BACKEND_URL` is where Python actually listens; the default matches
  // berg's own default port. Under `next dev` the same value is passed to the
  // client as NEXT_PUBLIC_API_BASE_URL, so streaming calls that bypass the
  // proxy still reach the right place.
  async rewrites() {
    const backend = process.env.BERG_BACKEND_URL || "http://127.0.0.1:8001";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`},
      {
        // Plugin UI bundles are served BY PYTHON, not by this app. Each
        // plugin's manifest gives an `entry_url` such as
        // `/berg-plugins/shared-todo/ui/dist/todo-surface.js`, and the browser
        // loads it directly — so without this rewrite the Plugins page renders
        // its chrome but the bundle 404s and the panel is empty (found
        // 2026-11-12 from a screenshot: 404 here, 200 on the backend).
        //
        // Not under /api/*, so it needs its own rule; and not a Next route, so
        // there is no precedence concern as there is with /api/orchestrator.
        source: "/berg-plugins/:path*",
        destination: `${backend}/berg-plugins/:path*`}];
  },

  distDir: "./dist",
  reactStrictMode: false,
  turbopack: {
    // Project root - prevents Next.js from using /home/nvidia as root
    root: import.meta.dirname,
    resolveAlias: {}},
  allowedDevOrigins: ["localhost", "127.0.0.1", "192.168.0.59"],
  compiler: {
    styledJsx: true,
    styledComponents: {
      ssr: true,
      fileName: true,
      minify: true,
      transpileTemplateLiterals: true,
      namespace: "berg-agents-app",
      cssProp: true}},

  // Cache Components (Next.js 16.3+): enables Partial Prerendering (PPR)
  // In dev mode, enables PPR for selective hydration testing.
  // In production (static export), disabled since PPR is incompatible with export mode.
  partialPrefetching: process.env.NODE_ENV !== "production",
  cacheComponents: process.env.NODE_ENV !== "production",

  // Webpack configuration for bundle optimization
  webpack: (config, { dev, isServer }) => {
    // Production optimizations (non-dev, client-side)
    if (!dev && !isServer) {
      config.optimization = {
        ...config.optimization,
        usedExports: true,
        sideEffects: false};
    }

    // Ignore node: protocol imports for browser compatibility
    config.resolve = {
      ...config.resolve,
      alias: {
        ...config.resolve.alias,
        "node:events": "events",
        "node:stream": "stream"}};

    return config;
  },

  // Image optimization for agent avatars and UI elements
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.heroui.com"},
      {
        protocol: "http",
        hostname: "localhost"}]},

  // ESLint configuration - moved to .eslintrc.json for Next.js 16 compatibility
  // eslint config now in separate file
};

export default withWorkflow(withBundleAnalyzer(nextConfig));
