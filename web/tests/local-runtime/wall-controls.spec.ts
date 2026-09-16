import { expect, test } from '@playwright/test';

const sceneFixture = {
  schemaVersion: 5 as const, revision: 1, id: 'scene-1', name: 'Wall',
  canvas: { width: 1600, height: 900, backgroundColor: '#000000' },
  sources: [
    { id: 'source-0', kind: 'color' as const, name: 'Source 0', color: '#101010', muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off' as const, audioTrack: 1, filters: [] },
    { id: 'source-1', kind: 'color' as const, name: 'Source 1', color: '#202020', muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off' as const, audioTrack: 1, filters: [] },
  ],
  items: [0, 1].map((index) => ({
    id: `item-${index}`, sourceId: `source-${index}`, x: index * 800, y: 0, width: 800, height: 450,
    scaleMode: 'contain' as const, crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: index,
    visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' as const,
  })),
};

test('exposes live large-picture controls, meter options and window preview', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async (scene) => {
    const { mountWall } = await import('/tests/harness/wallMount.tsx');
    const host = document.createElement('div');
    document.body.appendChild(host);
    const wall = mountWall(scene as never, host);
    const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    await wait(400);
    const findLabel = (text: string) => Array.from(host.querySelectorAll('label'))
      .find((label) => (label.textContent ?? '').includes(text));
    const largeMode = findLabel('大画面模式')?.querySelector('input') as HTMLInputElement | null;
    const countInput = findLabel('大画面数量')?.querySelector('input') as HTMLInputElement | null;
    const ratioInput = host.querySelector('input[aria-label="小画面与大画面比例"]') as HTMLInputElement | null;
    const mCheckbox = findLabel('M Source 0')?.querySelector('input') as HTMLInputElement | null;
    const before = { count: countInput?.value, ratio: ratioInput?.value, largeChecked: largeMode?.checked };
    mCheckbox?.click();
    await wait(120);
    const positions = Array.from(host.querySelectorAll('.direct-tile-position')).map((node) => (node as HTMLElement).style.width);
    if (ratioInput) {
      // React tracks the previous value, so drive the native setter first.
      const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      valueSetter?.call(ratioInput, '0.3');
      ratioInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    await wait(160);
    const ratioLabel = host.querySelector('[data-large-ratio]')?.textContent;
    const noAudioHint = Array.from(host.querySelectorAll('.audio-track-missing')).map((node) => node.textContent);
    const outputSelect = host.querySelector('select[aria-label="声音输出模式"]');
    // F5-02: no diagnostic button, state pill or name inside the picture; the
    // status rail lives outside the canvas and lists every visible source.
    const statusButtons = host.querySelectorAll('.tile-status-button').length;
    const statePills = host.querySelectorAll('.direct-tile-state').length;
    const tileNames = host.querySelectorAll('.direct-tile-name').length;
    const placeholders = host.querySelectorAll('.direct-tile-placeholder').length;
    const railButtons = host.querySelectorAll('.monitor-source-rail .source-status').length;
    const windowButton = Array.from(host.querySelectorAll('button')).find((button) => button.textContent === '窗口预览');
    windowButton?.click();
    await wait(120);
    const windowMode = Boolean(host.querySelector('.direct-preview-shell.window-preview-mode'));
    const controlsHidden = !host.querySelector('.monitor-view-controls');
    const barText = host.querySelector('.window-preview-bar')?.textContent ?? '';
    wall.unmount();
    return { before, afterCheck: { count: countInput?.value, largeChecked: largeMode?.checked }, positions, ratioLabel,
      noAudioHint, hasOutputSelect: Boolean(outputSelect), windowMode, controlsHidden, barText,
      statusButtons, statePills, tileNames, placeholders, railButtons };
  }, sceneFixture);

  expect(result.before).toEqual({ count: '0', ratio: '0.5', largeChecked: false });
  expect(result.afterCheck.count).toBe('1');
  expect(result.afterCheck.largeChecked).toBe(true);
  expect(new Set(result.positions).size).toBeGreaterThan(1);
  expect(result.ratioLabel).toBe('30%');
  expect(result.noAudioHint.length).toBe(2);
  expect(result.noAudioHint.every((value: string) => value === '该源没有音频轨道')).toBe(true);
  expect(result.hasOutputSelect).toBe(true);
  expect(result.windowMode).toBe(true);
  expect(result.controlsHidden).toBe(true);
  expect(result.barText).toContain('窗口预览');
  expect(result.statusButtons).toBe(0);
  expect(result.statePills).toBe(0);
  expect(result.tileNames).toBe(0);
  expect(result.placeholders).toBe(2);
  expect(result.railButtons).toBe(2);
});
