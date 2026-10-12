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
  reporter: [["list"], ["html", { open: "never" }]],

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
