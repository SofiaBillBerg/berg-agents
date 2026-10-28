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

import {defineConfig, globalIgnores} from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import unusedImports from "eslint-plugin-unused-imports";
import globals from "globals";
import tsParser from "@typescript-eslint/parser";

export default defineConfig(...nextVitals, [
    globalIgnores([
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
        "!**/.commitlintrc.cjs",
        "!**/.lintstagedrc.cjs",
        "!**/jest.config.js",
        "!**/plopfile.js",
        "!**/react-shim.js",
        "!**/tsup.config.ts"]),
    {
        plugins: {
            "unused-imports": unusedImports},

        languageOptions: {
            globals: {
                ...Object.fromEntries(
                    Object.entries(globals.browser).map(([key]) => [key, "off"]),
                ),
                ...globals.node},

            parser: tsParser,
            ecmaVersion: 12,
            sourceType: "module",

            parserOptions: {
                ecmaFeatures: {
                    jsx: true}}},

        settings: {
            react: {
                version: "detect"}},

        files: ["**/*.ts", "**/*.tsx"],

        rules: {
            "no-console": "warn",
            "react/prop-types": "off",
            "react/jsx-uses-react": "off",
            "react/react-in-jsx-scope": "off",
            "react-hooks/exhaustive-deps": "off",
            "jsx-a11y/click-events-have-key-events": "warn",
            "jsx-a11y/interactive-supports-focus": "warn",
            "no-unused-vars": "off",
            "unused-imports/no-unused-vars": "off",
            "unused-imports/no-unused-imports": "warn",

            "@typescript-eslint/no-unused-vars": [
                "warn",
                {
                    args: "after-used",
                    ignoreRestSiblings: false,
                    argsIgnorePattern: "^_.*?$"}],

            "import/order": [
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
                    reservedFirst: true}]}}]);
