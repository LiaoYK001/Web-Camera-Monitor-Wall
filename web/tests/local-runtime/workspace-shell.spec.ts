import { expect, test } from '@playwright/test';

test('shows the global OBS/classic mode picker and switches workspace style', async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'workspace-fixture', via: 'session' },
  }));
  await page.goto('/');

  const picker = page.getByRole('group', { name: '工作区风格' });
  await expect(picker).toBeVisible();
  const classicButton = picker.getByRole('button', { name: '经典' });
  await expect(picker.getByRole('button', { name: 'OBS 风格' })).toHaveAttribute('aria-pressed', 'true');
  await expect(classicButton).toHaveAttribute('aria-pressed', 'false');

  await classicButton.click();
  await expect(classicButton).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.workspace-shell')).toHaveAttribute('data-workspace-style', 'classic');
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe('');

  await page.reload();
  await expect(page.locator('.workspace-shell')).toHaveAttribute('data-workspace-style', 'classic');
  const reloadedClassicButton = page.getByRole('group', { name: '工作区风格' }).getByRole('button', { name: '经典' });
  await expect(reloadedClassicButton).toHaveAttribute('aria-pressed', 'true');

  const reloadedObsButton = page.getByRole('group', { name: '工作区风格' }).getByRole('button', { name: 'OBS 风格' });
  await reloadedObsButton.click();
  await expect(reloadedObsButton).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.workspace-shell')).toHaveAttribute('data-workspace-style', 'obs');
});

test('keeps long workspace pages reachable through the document scrollbar', async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'scroll-fixture', via: 'session' },
  }));
  await page.goto('/');

  const metrics = await page.evaluate(() => {
    const probe = document.createElement('div');
    probe.style.height = '180vh';
    probe.setAttribute('data-scroll-probe', 'true');
    document.body.append(probe);
    const result = {
      bodyOverflowY: getComputedStyle(document.body).overflowY,
      htmlOverflowY: getComputedStyle(document.documentElement).overflowY,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
    };
    probe.remove();
    return result;
  });

  expect(metrics.bodyOverflowY).toBe('auto');
  expect(metrics.htmlOverflowY).toBe('auto');
  expect(metrics.scrollHeight).toBeGreaterThan(metrics.viewportHeight);
});

test('allows the device catalog to scroll past the first viewport', async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'catalog-fixture', via: 'session' },
  }));
  await page.route('**/api/v2/source-catalog*', (route) => route.fulfill({
    json: {
      schemaVersion: 2, page: 1, limit: 256, total: 30,
      items: Array.from({ length: 30 }, (_, index) => ({
        schemaVersion: 2, id: `camera-${index}`, name: `Camera ${index}`, kind: 'camera', adapter: 'rtsp',
        enabled: true, groupId: '', tags: [], addressDisplay: `rtsp://camera-${index}/live`, health: 'online',
        hardwareDecode: 'auto', profileCount: 1, trackCount: 1,
        deviceCapabilities: { ptz: false, snapshot: false, talk: false }, profiles: [], revision: 1,
        createdAt: 0, updatedAt: 0,
      })),
    },
  }));
  await page.goto('/#/devices');
  await expect(page.getByRole('heading', { name: '设备与来源' })).toBeVisible();

  const before = await page.evaluate(() => window.scrollY);
  await page.mouse.wheel(0, 900);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(before);
});

test('offers a guided import for sources that still live in the legacy Studio file', async ({ page }) => {
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({
    json: { authenticated: true, user: 'legacy-fixture', via: 'session' },
  }));
  await page.route('**/api/v2/source-catalog*', (route) => route.fulfill({
    json: { schemaVersion: 2, page: 1, limit: 256, total: 0, items: [] },
  }));
  let imported = false;
  await page.route('**/api/v2/source-catalog/legacy-import', async (route) => {
    if (route.request().method() === 'POST') {
      imported = true;
      await route.fulfill({ json: { schemaVersion: 1, baseRevision: 2, items: [{ sourceId: 'old-front', state: 'linked', cameraId: 'legacy-front', profileId: 'main' }] } });
      return;
    }
    await route.fulfill({ json: imported
      ? { schemaVersion: 1, baseRevision: 2, count: 2, items: [
        { sourceId: 'old-front', state: 'linked', cameraId: 'legacy-front', profileId: 'main' },
        { sourceId: 'old-secret', state: 'needs_configuration', reason: 'embedded_credentials_require_secret_reference' },
      ] }
      : { schemaVersion: 1, baseRevision: 1, count: 2, items: [
        { sourceId: 'old-front', state: 'ready_to_import' },
        { sourceId: 'old-secret', state: 'needs_configuration', reason: 'embedded_credentials_require_secret_reference' },
      ] } });
  });
  await page.goto('/#/devices');
  await page.getByRole('button', { name: '检查旧 Studio 来源' }).click();
  await expect(page.getByRole('status')).toContainText('可导入 1');
  await expect(page.getByRole('status')).toContainText('需配置 1');
  await page.getByRole('button', { name: '导入可安全关联项' }).click();
  await expect(page.getByRole('status')).toContainText('已关联 1');
});
