import { expect, test } from '@playwright/test';

const sceneFixture = {
  schemaVersion: 5,
  revision: 1,
  id: 'projector-fixture',
  name: 'Projector fixture',
  canvas: { width: 1920, height: 1080, backgroundColor: '#000000' },
  sources: [{
    id: 'source-0', kind: 'color', name: 'Source 0', color: '#101820',
    muted: true, volume: 0, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [],
  }],
  items: [{
    id: 'item-0', sourceId: 'source-0', x: 0, y: 0, width: 1920, height: 1080, scaleMode: 'contain',
    crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: 0,
    visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal',
  }],
};

/** Keeps the projector tests off the media plane and free of real negotiation. */
async function mockBackend(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'projector-fixture', via: 'session' },
  }));
  await page.route('**/api/v1/scene', (route) => route.fulfill({ json: sceneFixture }));
  await page.route('**/api/v1/program/status', (route) => route.fulfill({ json: { enabled: false } }));
  await page.route('**/api/v1/program/whep', (route) => route.fulfill({ status: 503, json: {} }));
  await page.route('**/api/v1/playback/capabilities', (route) => route.fulfill({ json: { sources: [] } }));
  await page.route('**/api/v1/cameras', (route) => route.fulfill({ json: { cameras: [] } }));
  await page.route('**/api/v2/source-catalog*', (route) => route.fulfill({
    json: { schemaVersion: 2, page: 1, limit: 256, total: 0, items: [] },
  }));
}

test('projector route shows the final picture without the workspace shell', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/#projector');

  const projector = page.locator('.projector-shell');
  await expect(projector).toHaveAttribute('data-projector-mode', 'direct');
  await expect(projector.locator('.direct-preview')).toBeVisible();
  // The detached window must never be a second copy of the wall.
  await expect(page.locator('.workspace-shell')).toHaveCount(0);
  await expect(projector.locator('.monitor-view-controls')).toHaveCount(0);
  await expect(projector.locator('.monitor-source-rail')).toHaveCount(0);
});

test('composite projector shows only the program picture', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/#projector-composite');

  const projector = page.locator('.projector-shell');
  await expect(projector).toHaveAttribute('data-projector-mode', 'composite');
  await expect(projector.locator('.program-preview')).toHaveCount(1);
  await expect(projector.locator('.program-preview video')).toHaveCount(1);
  await expect(page.locator('.workspace-shell')).toHaveCount(0);
  // Diagnostics stay on the wall; the projector keeps the in-frame status chip.
  await expect(projector.locator('.program-diagnostics')).toBeHidden();
});

test('ordinary routes keep the full workspace shell', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/#monitor');

  await expect(page.locator('.workspace-shell')).toHaveCount(1);
  await expect(page.locator('.projector-shell')).toHaveCount(0);
});

test('resolves the projector route and opens a reusable detached window', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/');

  const result = await page.evaluate(async () => {
    const projector = await import('/src/projector.ts');
    const opened: string[] = [];
    const original = window.open;
    window.open = ((url?: string | URL, name?: string, features?: string) => {
      opened.push([String(url), String(name), String(features)].join('|'));
      return null;
    }) as typeof window.open;
    try {
      projector.openProjectorWindow('direct');
      projector.openProjectorWindow('composite');
    } finally {
      window.open = original;
    }
    return {
      opened,
      modes: [
        projector.projectorModeFromHash('#projector'),
        projector.projectorModeFromHash('#/projector-composite'),
        projector.projectorModeFromHash('#projector?mode=composite'),
        projector.projectorModeFromHash('#monitor'),
      ],
    };
  });

  expect(result.modes).toEqual(['direct', 'composite', 'direct', null]);
  expect(result.opened).toHaveLength(2);
  expect(result.opened[0]).toMatch(/^\/#projector\|webobs-projector-direct\|/);
  expect(result.opened[1]).toMatch(/^\/#projector-composite\|webobs-projector-composite\|/);
});
