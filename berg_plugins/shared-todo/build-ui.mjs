/**
 * Build the shared-todo plugin UI as a self-contained ES module.
 *
 * The host loads the output at runtime from
 * /berg-plugins/shared-todo/ui/dist/todo-surface.js (see the `ui:`
 * block in plugin.yaml), so this bundle is the plugin's own artifact —
 * the host never imports plugin source.
 *
 * React, ReactDOM and HeroUI are EXTERNALS mapped onto the host's
 * `window.BergRuntime` rather than bundled. That is what guarantees a
 * single React instance: a plugin bringing its own React copy would
 * break hooks the moment the host rendered it.
 *
 *   bun run build:ui
 */

import esbuild from "esbuild";
import path from "node:path";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// NOTE: this script lives in the PACKAGE ROOT, so `here` is the root.
const pkgRoot = here;

/** Host runtime globals the plugin's bundle resolves against. */
const runtimeGlobals = {
  name: "berg-runtime-globals",
  setup(build) {
    // React itself + the JSX runtime the TSX transform emits.
    build.onResolve({filter: /^react$/}, () => ({
      path: "react",
      namespace: "berg-runtime"}));
    build.onResolve({filter: /^react\/jsx-runtime$/}, () => ({
      path: "react/jsx-runtime",
      namespace: "berg-runtime"}));
    build.onResolve({filter: /^react\/jsx-dev-runtime$/}, () => ({
      path: "react/jsx-dev-runtime",
      namespace: "berg-runtime"}));
    build.onResolve({filter: /^react-dom$/}, () => ({
      path: "react-dom",
      namespace: "berg-runtime"}));
    build.onResolve({filter: /^react-dom\/client$/}, () => ({
      path: "react-dom/client",
      namespace: "berg-runtime"}));
    // Everything else the surface imports (HeroUI, icons, ...).
    build.onResolve({filter: /.*/}, (args) => {
      if (args.kind === "entry-point") return null;
      if (!args.path.startsWith(".") && !path.isAbsolute(args.path)) {
        return {path: args.path, namespace: "berg-runtime"};
      }
      return null;
    });

    build.onLoad({filter: /.*/, namespace: "berg-runtime"}, (args) => ({
      contents: `module.exports = window.BergRuntime.require(${JSON.stringify(
        args.path,
      )});`,
      loader: "js"}));
  }};

await esbuild.build({
  entryPoints: [path.join(pkgRoot, "ui", "TodoSurface.tsx")],
  outfile: path.join(pkgRoot, "ui", "dist", "todo-surface.js"),
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2020"],
  jsx: "automatic",
  // Externals are injected by the plugin above, so nothing from
  // node_modules is duplicated into the plugin bundle.
  plugins: [runtimeGlobals],
  logLevel: "info",
  minify: true,
  sourcemap: true});

console.log("built ui/dist/todo-surface.js");
