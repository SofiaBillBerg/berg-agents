/** @type {import('next').NextConfig} */

const nextConfig = {
  // Static export only in production (FastAPI mounts dist/). In dev, Next needs server mode for HMR + API proxy.
  output: process.env.NODE_ENV === "production" ? "export" : undefined,
  distDir: "./dist",
  reactStrictMode: false,
  turbopack: {
    // Project root — prevents Next.js from using /home/nvidia as root
    root: import.meta.dirname,
    // Additional safeguard: enforce lookup from this directory
    resolveAlias: {},
  },
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  compiler: {
    styledJsx: true,
    // see https://styled-components.com/docs/tooling#babel-plugin for more info on the options.
    styledComponents: {
      ssr: true,
      // Enabled by default.
      fileName: true,
      // Enabled by default.
      minify: true,
      // Enabled by default.
      transpileTemplateLiterals: true,
      // Empty by default.
      namespace: "berg-agents-app",
      // Enabled by default.
      cssProp: true,
    },
  },
};
export default nextConfig;
