/** @type {import('next').NextConfig} */

// Bundle analyzer for Phase 2 performance monitoring
// Enable with: ANALYZE=true npm run build
const withBundleAnalyzer = process.env.ANALYZE === 'true'
  ? (await import('@next/bundle-analyzer')).default({
      enabled: process.env.ANALYZE === 'true',
      compression: false,
    })
  : (config) => config;

const nextConfig = {
  // Static export only in production (FastAPI mounts dist/). In dev, Next needs server mode for HMR + API proxy.
  output: process.env.NODE_ENV === "production" ? "export" : undefined,
  distDir: "./dist",
  reactStrictMode: false,
  turbopack: {
    // Project root — prevents Next.js from using /home/nvidia as root
    root: import.meta.dirname,
    resolveAlias: {},
  },
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  compiler: {
    styledJsx: true,
    styledComponents: {
      ssr: true,
      fileName: true,
      minify: true,
      transpileTemplateLiterals: true,
      namespace: "berg-agents-app",
      cssProp: true,
    },
  },

  // Cache Components (Next.js 16.3+): enables Partial Prerendering (PPR)
  // In dev mode, enables PPR for selective hydration testing.
  // In production (static export), disabled since PPR is incompatible with export mode.
  cacheComponents: process.env.NODE_ENV !== 'production',

  // Webpack configuration for bundle optimization
  webpack: (config, { dev, isServer }) => {
    // Production optimizations (non-dev, client-side)
    if (!dev && !isServer) {
      config.optimization = {
        ...config.optimization,
        usedExports: true,
        sideEffects: false,
      };
    }

    // Ignore node: protocol imports for browser compatibility
    config.resolve = {
      ...config.resolve,
      alias: {
        ...config.resolve.alias,
        'node:events': 'events',
        'node:stream': 'stream',
      },
    };

    return config;
  },

  // Image optimization for agent avatars and UI elements
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '*.heroui.com',
      },
      {
        protocol: 'http',
        hostname: 'localhost',
      },
    ],
  },

  // ESLint configuration — moved to .eslintrc.json for Next.js 16 compatibility
  // eslint config now in separate file
};

export default withBundleAnalyzer(nextConfig);