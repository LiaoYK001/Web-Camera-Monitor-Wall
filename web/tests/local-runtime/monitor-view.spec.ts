import { expect, test } from '@playwright/test';

test('generates stable bounded Scene v5 layouts for every 1-16 and M/S combination', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const monitor = await import('/src/monitorView.ts');
    const failures: string[] = [];
    for (const portrait of [false, true]) for (let count = 1; count <= 16; count += 1) {
      for (let largeCount = 0; largeCount <= count; largeCount += 1) {
        const width = portrait ? 900 : 1600; const height = portrait ? 1600 : 900;
        const scene = {
          schemaVersion: 5 as const, revision: 1, id: 'fixture', name: 'fixture',
          canvas: { width, height, backgroundColor: '#000000' },
          sources: Array.from({ length: count }, (_, index) => ({
            id: `source-${index}`, kind: 'color' as const, name: `Source ${index}`, color: '#000000',
            muted: true, volume: 0, syncOffsetMs: 0, monitoring: 'off' as const, audioTrack: 1, filters: [],
          })),
          items: Array.from({ length: count }, (_, index) => ({
            id: `item-${index}`, sourceId: `source-${index}`, x: 0, y: 0, width: 1, height: 1,
            scaleMode: 'contain' as const, crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: index,
            visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' as const,
          })),
        };
        const view = monitor.defaultMonitorView(); view.largeCount = largeCount;
        const laidOut = monitor.applyAutomaticLayout(scene, view);
        for (const item of laidOut.items) if (item.x < 0 || item.y < 0 || item.width <= 0 || item.height <= 0 ||
          item.x + item.width > width + .001 || item.y + item.height > height + .001)
          failures.push(`${portrait}/${count}/${largeCount}:bounds`);
        for (let left = 0; left < laidOut.items.length; left += 1) for (let right = left + 1; right < laidOut.items.length; right += 1) {
          const a = laidOut.items[left], b = laidOut.items[right];
          if (a.x < b.x + b.width - .001 && a.x + a.width > b.x + .001 &&
              a.y < b.y + b.height - .001 && a.y + a.height > b.y + .001)
            failures.push(`${portrait}/${count}/${largeCount}:overlap`);
        }
        if (largeCount > 0 && largeCount < count) {
          const largeArea = laidOut.items[0].width * laidOut.items[0].height;
          const smallArea = laidOut.items[largeCount].width * laidOut.items[largeCount].height;
          if (largeArea <= smallArea) failures.push(`${portrait}/${count}/${largeCount}:large-not-larger`);
        }
        const repeated = monitor.applyAutomaticLayout(laidOut, view);
        if (JSON.stringify(laidOut.items) !== JSON.stringify(repeated.items)) failures.push(`${portrait}/${count}/${largeCount}:unstable`);
      }
    }
    return failures;
  });
  expect(result).toEqual([]);
});

test('keeps low-power selection and analytics signals fail-closed', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const monitor = await import('/src/monitorView.ts');
    const telemetry = await import('/src/mediaTelemetry.ts');
    const profiles = [
      { id: 'main', name: 'Main', role: 'main' as const, endpoint: '', videoCodec: 'h265', audioCodec: '', width: 1920, height: 1080, fps: 25 },
      { id: 'sub', name: 'Sub', role: 'sub' as const, endpoint: '', videoCodec: 'h264', audioCodec: '', width: 640, height: 360, fps: 5 },
      { id: 'snapshot', name: 'Snapshot', role: 'snapshot' as const, endpoint: '', videoCodec: 'jpeg', audioCodec: '', width: 320, height: 180, fps: 1 },
    ];
    const met = monitor.selectLowPowerProfile(profiles, 2);
    const unmet = monitor.selectLowPowerProfile(profiles.slice(0, 2), 2);
    const valid = monitor.validDetectionSignal({ schemaVersion: 1, cameraId: 'cam-1', profileId: 'sub', kind: 'motion', occurredAt: Date.now(), confidence: .8, source: 'browser' });
    const invalid = monitor.validDetectionSignal({ schemaVersion: 1, cameraId: 'cam-1', profileId: 'sub', kind: 'person', occurredAt: Date.now(), confidence: 2, boxes: [{ x: .9, y: 0, width: .2, height: 1 }], source: 'browser' });
    const sources = ['a', 'b', 'c', 'd', 'e']; let bag: string[] = [];
    const first = monitor.nextRotationWindow(sources, [], 3, ['a'], 'random', bag, () => 0); bag = first.bag;
    const second = monitor.nextRotationWindow(sources, first.selection, 3, ['a'], 'random', bag, () => 0);
    const sequential = monitor.nextRotationWindow(sources, ['a', 'b'], 2, ['a'], 'sequential');
    return { met: met.profile?.id, metOk: met.targetMet, unmet: unmet.profile?.id, unmetOk: unmet.targetMet,
      reason: unmet.reason, valid, invalid, first: first.selection, second: second.selection,
      randomUnique: new Set([...first.selection.slice(1), ...second.selection.slice(1)]).size,
      sequential: sequential.selection, overlay: monitor.defaultTelemetryOverlay(),
      unavailableText: telemetry.formatTelemetry({ fps: null, bytesPerSecond: null, codec: 'MJPEG', decoder: 'Unknown' }, ['fps', 'bitrate', 'codec', 'decoder']) };
  });
  expect(result).toEqual({ met: 'snapshot', metOk: true, unmet: 'sub', unmetOk: false,
    reason: 'no_low_frame_rate_profile', valid: true, invalid: false,
    first: ['a', 'c', 'd'], second: ['a', 'e', 'b'], randomUnique: 4, sequential: ['a', 'c'],
    overlay: { enabled: false, fields: ['fps', 'bitrate', 'codec', 'decoder'], position: 'bottom-left', customX: 0,
      customY: 1, textOpacity: .9, backgroundEnabled: true, backgroundColor: '#000000', backgroundOpacity: .45,
      refreshIntervalMs: 1000 },
    unavailableText: 'FPS — · Speed — · MJPEG · Unknown' });
});
