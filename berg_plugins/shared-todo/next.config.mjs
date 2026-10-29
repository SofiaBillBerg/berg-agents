/**
 * Next.js config for the shared-todo plugin UI.
 *
 * Two modes, so the plugin can be developed alone AND consumed by the
 * host:
 *
 * - Standalone (default): a real Next dev/build, for working on the
 *   todo surface in isolation. Static export stays off so HMR and the
 *   dev server work.
 * - Host build: the host (berg_agents/ui/webapp) imports this
 *   plugin's `ui/TodoSurface.tsx` into its own build graph, so nothing
 *   here is emitted for that path — see `LINKED_INTO_HOST`.
 *
 * API_BASE follows the host convention: empty means same-origin.
 */

const LINKED_INTO_HOST = process.env.BERG_PLUGIN_LINKED_INTO_HOST === "1";

/** @type {import('next').NextConfig} */
const nextConfig = {
    // NOTE: never `output: "export"`. The plugin UI is a component the
    // host renders, and this app's own build exists only for dev/HMR.
    distDir: "./dist",
    reactStrictMode: false,
    turbopack: {
        // Keeps Next from walking up to a parent package.json for root.
        root: import.meta.dirname,
        resolveAlias: {}},
    allowedDevOrigins: ["localhost", "127.0.0.1"],
    compiler: {
        styledJsx: true,
        styledComponents: {
            ssr: true,
            fileName: true,
            minify: true,
            transpileTemplateLiterals: true,
            namespace: "berg-plugin-shared-todo",
            cssProp: true}},

    webpack: (config, {dev, isServer}) => {
        // Production optimizations (non-dev, client-side).
        if (!dev && !isServer) {
            config.optimization = {
                ...config.optimization,
                usedExports: true,
                sideEffects: false};
        }

        // Ignore node: protocol imports for browser compatibility.
        config.resolve = {
            ...config.resolve,
            alias: {
                ...config.resolve.alias,
                "node:events": "events",
                "node:stream": "stream"}};

        return config;
    },

    images: {
        remotePatterns: [
            {
                protocol: "https",
                hostname: "*.heroui.com"},
            {
                protocol: "http",
                hostname: "localhost"}]}};

// `output: "export"` is deliberately never set — see the header note.
export default nextConfig;
void LINKED_INTO_HOST;
