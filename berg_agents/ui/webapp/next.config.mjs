/** @type {import('next').NextConfig} */

const nextConfig = {
    output: "export",
    distDir: "./dist",
    reactStrictMode: false,
    turbopack: {
    },    allowedDevOrigins: ['10.255.255.254'],
compiler: {
    styledJsx: true,
        // see https://styled-components.com/docs/tooling#babel-plugin for more info on the options.
        styledComponents: {

            ssr: true,
            // Enabled by default.
            fileName: true,
            // Enabled by default.
            minify:true,
            // Enabled by default.
            transpileTemplateLiterals:true,
            // Empty by default.
            namespace:"berg-agents-web",
            // Enabled by default.
            cssProp:true,
        },
    },
}
module.exports = nextConfig;
