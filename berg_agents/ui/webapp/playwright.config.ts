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
 * Playwright configuration for visual regression testing.
 * Captures baseline screenshots and compares against them.
 */
import {defineConfig, devices} from "@playwright/test";

export default defineConfig({
    testDir: "./app/__tests__",
    outputDir: "./test-results",
    snapshotDir: "./__screenshots__/baseline",
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    workers: process.env.CI ? 1 : undefined,
    reporter: [["list"], ["html", {open: "never"}]],

    use: {
        baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
        trace: "on-first-retry",
        screenshot: "off", // We use explicit toMatchSnapshot below
    },

    // Only run files matching visual test patterns
    testMatch: ["**/*.visual.test.ts", "**/*.test.ts"],

    projects: [
        {
            name: "chromium",
            use: {
                ...devices["Desktop Chrome"]}},
        {
            name: "firefox",
            use: {
                ...devices["Desktop Firefox"]}},
        {
            name: "Mobile Chrome",
            use: {
                ...devices["Pixel 5"]}}]});
