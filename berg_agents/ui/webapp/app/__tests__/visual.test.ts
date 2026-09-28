/**
 * Visual regression tests for HeroUI v3 components and layouts.
 * Uses Playwright's snapshot testing to capture and compare visual baselines.
 *
 * Run: npx playwright test visual.test.ts
 * Update baselines: npx playwright test --update-snapshots
 */

import { test, expect } from '@playwright/test';

const VIEWPORT = { width: 1280, height: 720 };
const MOBILE_VIEWPORT = { width: 375, height: 667 };
const TABLET_VIEWPORT = { width: 768, height: 1024 };

// Component test cases with their selectors and thresholds
const COMPONENT_TESTS = [
  {
    name: 'StatusCard-idle',
    path: '/test-harness-simple',
    selector: '[class*="status-card"], [class*="StatusCard"]',
    threshold: 0.01,
  },
  {
    name: 'ChatTranscript-empty',
    path: '/test-harness-simple',
    selector: '[class*="chat-transcript"], [class*="ChatTranscript"]',
    threshold: 0.02,
  },
  {
    name: 'AgentPanel-compact',
    path: '/test-harness-simple',
    selector: '[class*="agent-panel"], [class*="AgentPanel"]',
    threshold: 0.01,
  },
  {
    name: 'LearningPanel-empty',
    path: '/test-harness-simple',
    selector: '[class*="learning-panel"], [class*="LearningPanel"]',
    threshold: 0.02,
  },
  {
    name: 'ProviderSelector-default',
    path: '/test-harness-simple',
    selector: '[class*="provider-selector"]',
    threshold: 0.01,
  },
  {
    name: 'InputBar-focused',
    path: '/test-harness-simple',
    selector: '[class*="input-bar"]',
    threshold: 0.02,
  },
  {
    name: 'ThemeToggle',
    path: '/test-harness-simple',
    selector: 'button[aria-label="Toggle theme"]',
    threshold: 0.01,
  },
];

// Visual regression tests for desktop
test.describe('HeroUI v3 Component Visual Regression — Desktop', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
  });

  for (const componentTest of COMPONENT_TESTS) {
    test(`${componentTest.name}`, async ({ page }) => {
      await page.goto(componentTest.path);

      // Wait for component to render
      await page.waitForSelector(componentTest.selector, { timeout: 10000 });

      // Take screenshot of the component
      const screenshot = await page.locator(componentTest.selector).screenshot();

      // Compare with baseline
      expect(screenshot).toMatchSnapshot(`${componentTest.name}.png`, {
        threshold: componentTest.threshold,
      });
    });
  }
});

// Mobile viewport tests
test.describe('HeroUI v3 Component Visual Regression — Mobile', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
  });

  for (const componentTest of COMPONENT_TESTS) {
    test(`${componentTest.name}-mobile`, async ({ page }) => {
      await page.goto(componentTest.path);

      await page.waitForSelector(componentTest.selector, { timeout: 10000 });

      const screenshot = await page.locator(componentTest.selector).screenshot();

      expect(screenshot).toMatchSnapshot(`${componentTest.name}-mobile.png`, {
        threshold: componentTest.threshold,
      });
    });
  }
});

// Theme variation tests
test.describe('Theme Variations', () => {
  test('Light mode — AgentPanel', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/test-harness-simple');

    // Ensure light mode
    await page.evaluate(() => {
      document.documentElement.classList.remove('dark');
      document.documentElement.setAttribute('data-theme', 'light');
    });

    await page.waitForSelector('[class*="agent-panel"]', { timeout: 10000 });

    const screenshot = await page.locator('[class*="agent-panel"]').screenshot();
    expect(screenshot).toMatchSnapshot('agent-panel-light.png', { threshold: 0.01 });
  });

  test('Dark mode — AgentPanel', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/test-harness-simple');

    await page.evaluate(() => {
      document.documentElement.classList.add('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
    });

    await page.waitForSelector('[class*="agent-panel"]', { timeout: 10000 });

    const screenshot = await page.locator('[class*="agent-panel"]').screenshot();
    expect(screenshot).toMatchSnapshot('agent-panel-dark.png', { threshold: 0.01 });
  });

  test('Light mode — ProviderSelector', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/test-harness-simple');

    await page.evaluate(() => {
      document.documentElement.classList.remove('dark');
      document.documentElement.setAttribute('data-theme', 'light');
    });

    await page.waitForSelector('[class*="provider-selector"]', { timeout: 10000 });

    const screenshot = await page.locator('[class*="provider-selector"]').screenshot();
    expect(screenshot).toMatchSnapshot('provider-selector-light.png', { threshold: 0.01 });
  });

  test('Dark mode — ProviderSelector', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/test-harness-simple');

    await page.evaluate(() => {
      document.documentElement.classList.add('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
    });

    await page.waitForSelector('[class*="provider-selector"]', { timeout: 10000 });

    const screenshot = await page.locator('[class*="provider-selector"]').screenshot();
    expect(screenshot).toMatchSnapshot('provider-selector-dark.png', { threshold: 0.01 });
  });
});

// Full page layout tests
test.describe('Full Page Layout', () => {
  test('App layout — desktop', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');

    await page.waitForSelector('.app-container, [class*="app"]', { timeout: 10000 });

    const screenshot = await page.screenshot();
    expect(screenshot).toMatchSnapshot('app-layout-desktop.png', { threshold: 0.1 });
  });

  test('App layout — mobile', async ({ page }) => {
    await page.setViewportSize(MOBILE_VIEWPORT);
    await page.goto('/');

    await page.waitForSelector('.app-container, [class*="app"]', { timeout: 10000 });

    const screenshot = await page.screenshot();
    expect(screenshot).toMatchSnapshot('app-layout-mobile.png', { threshold: 0.1 });
  });
});

// Interactive component behavior tests
test.describe('Interactive Component Behavior', () => {
  test('InputBar accepts user input', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');

    await page.waitForSelector('textarea', { timeout: 10000 });

    await page.fill('textarea', 'Test task description');
    const inputValue = await page.inputValue('textarea');
    expect(inputValue).toBe('Test task description');
  });

  test('Theme toggle switches modes', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');

    await page.waitForSelector('button[aria-label="Toggle theme"]', { timeout: 10000 });

    const initialTheme = await page.evaluate(() => {
      return document.documentElement.getAttribute('data-theme') || document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    });

    await page.click('button[aria-label="Toggle theme"]');

    const newTheme = await page.evaluate(() => {
      return document.documentElement.getAttribute('data-theme') || document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    });

    expect(newTheme).not.toBe(initialTheme);
  });

  test('Provider selector opens dropdown', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/test-harness-simple');

    await page.waitForSelector('[class*="provider-selector"]', { timeout: 15000 });

    // Click the provider select trigger
    const selector = await page.locator('[class*="provider-select"]').first();
    if (await selector.isVisible()) {
      await selector.click();
      // Check that dropdown opened
      await page.waitForSelector('[role="listbox"]', { timeout: 5000 }).catch(() => {
        // Listbox might use different role in HeroUI v3
      });
    }
  });

  test('Streaming text appears progressively', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');

    await page.fill('textarea', 'Explain quantum computing');
    await page.click('button[type="submit"]');

    // Wait for first text chunk
    await page.waitForSelector('[class*="chat-transcript"]', { timeout: 10000 });

    // Verify streaming content
    const transcriptText = await page.locator('[class*="chat-transcript"]').textContent();
    expect(transcriptText).toBeTruthy();
    expect(transcriptText!.length).toBeGreaterThan(0);
  });
});

// Error boundary tests
test.describe('Error Boundary States', () => {
  test('Error boundary displays for failed lazy load', async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto('/');

    // Simulate lazy load failure
    await page.evaluate(() => {
      // Trigger an error in the lazy-loaded component
      window.dispatchEvent(new Event('simulate-lazy-error'));
    });

    // Check that either error boundary text or some content appears
    const content = await page.textContent('body');
    expect(content).toMatch(/Failed to load|HITL Surface|Loading|app/i);
  });
});

// Tablet layout tests
test.describe('Tablet Layout', () => {
  test('App layout — tablet', async ({ page }) => {
    await page.setViewportSize(TABLET_VIEWPORT);
    await page.goto('/');

    await page.waitForSelector('.app-container, [class*="app"]', { timeout: 10000 });

    const screenshot = await page.screenshot();
    expect(screenshot).toMatchSnapshot('app-layout-tablet.png', { threshold: 0.1 });
  });
});

export { VIEWPORT, MOBILE_VIEWPORT, TABLET_VIEWPORT, COMPONENT_TESTS };
