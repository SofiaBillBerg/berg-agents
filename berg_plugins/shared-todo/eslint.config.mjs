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
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import jestPlugin from "eslint-plugin-jest";
import tseslint from "typescript-eslint";
import importPlugin from "eslint-plugin-import-x";
import unusedImports from "eslint-plugin-unused-imports";
import globals from "globals";
import nextPlugin from "@next/eslint-plugin-next";
import reactPlugin from "eslint-plugin-react";
import hooksPlugin from "eslint-plugin-react-hooks";
import jsxA11yPlugin from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import prettier from "eslint-config-prettier/flat";
import eslintNextPlugin from "@next/eslint-plugin-next";

export default tseslint.config(
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
  {
    ignores: [
      ".now/*",
      "**/*.css",
      "**/.changeset",
      "**/dist",
      "esm/*",
      "public/*",
      "tests/*",
      "scripts/*",
      "**/*.config.js",
      "**/.DS_Store",
      "**/node_modules",
      "**/coverage",
      "**/.next",
      "**/build",
      "**/*config*.mjs",
      "**/*dir*.mjs",
      "**/*.config.js",
      "**/.DS_Store",
      "**/node_modules",
      "**/coverage",
      "**/.next",
      "**/build",
      "**/_site",
      "**/apidocs",
      "**/_extensions",
      "**/.venv",
      "**/*cache*",
      "**/rvenv*",
      ".*/",
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts"],
    plugins: {
      "unused-imports": unusedImports,
      "@typescript-eslint": tseslint.plugin,
      "@next/next": nextPlugin,
      react: reactPlugin,
      "react-hooks": hooksPlugin,
      "jsx-a11y": jsxA11yPlugin,
      "eslint-next": eslintNextPlugin,
      "import-x": importPlugin},
    languageOptions: {
      parser: tseslint.parser,
      //   ecmaVersion: 12,
      sourceType: "module",
      globals: {
        ...Object.fromEntries(
          Object.entries(globals.browser).map(([key]) => [key, "off"]),
        ),
        ...globals.node},
      parserOptions: {
        ecmaFeatures: {
          jsx: true}}},
    settings: {
      react: {
        version: "detect"}},
    extends: [
      tseslint.configs.recommended,
      prettier,
      js.configs.recommended,
      reactHooks.configs.flat["recommended-latest"]],
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      "no-html-link-for-pages": "off",
      "no-console": "off",
      "react/prop-types": "off",
      "react/jsx-uses-react": "off",
      "react/react-in-jsx-scope": "off",
      "react-hooks/exhaustive-deps": "off",
      "jsx-a11y/click-events-have-key-events": "warn",
      "jsx-a11y/interactive-supports-focus": "warn",
      "no-unused-vars": "off",
      "unused-imports/no-unused-vars": "off",
      "@typescript-eslint/no-unused-expressions": "off",
      "unused-imports/no-unused-imports": "warn",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          args: "after-used",
          ignoreRestSiblings: true,
          reportUsedIgnorePattern: false,
          ignoreUsingDeclarations: true,
          argsIgnorePattern: "^_.*?$"}],

      "import-x/order": [
        "warn",
        {
          groups: [
            "type",
            "builtin",
            "object",
            "external",
            "internal",
            "parent",
            "sibling",
            "index"],
          pathGroups: [
            {
              pattern: "~/**",
              group: "external",
              position: "after"}],
          "newlines-between": "always"}],

      "react/self-closing-comp": "warn",
      "react/jsx-sort-props": [
        "warn",
        {
          callbacksLast: true,
          shorthandFirst: true,
          noSortAlphabetically: false,
          reservedFirst: true}]}},
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    languageOptions: {
      globals: globals.browser}},
);
