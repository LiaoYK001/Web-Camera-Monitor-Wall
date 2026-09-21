#!/usr/bin/env node
/** Plays a local H264 file in the same headless Chromium and reports the
 *  decoded/presented frame rate. Removes MediaMTX, WebRTC and the network from
 *  the picture, so it tells whether the ~15 fps ceiling is the browser itself. */
import { chromium } from '@playwright/test';
const file = process.argv[2];
const seconds = Number(process.argv[3] ?? 15);
const channel = process.env.WHEP_PROBE_CHANNEL;
const browser = await chromium.launch({
  ...(channel ? { channel } : {}),
  args: ['--autoplay-policy=no-user-gesture-required'],
});
const page = await browser.newPage();
await page.goto('file://' + file);
await page.waitForSelector('video', { timeout: 15000 });
const result = await page.evaluate(async (seconds) => {
  const video = document.querySelector('video');
  video.muted = true;
  video.play().catch(() => undefined);
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const deadline = performance.now() + 15000;
  while (performance.now() < deadline && (video.readyState < 2 || video.videoWidth === 0)) await wait(250);
  const before = video.getVideoPlaybackQuality();
  const startedAt = performance.now();
  await wait(seconds * 1000);
  const after = video.getVideoPlaybackQuality();
  const elapsed = (performance.now() - startedAt) / 1000;
  return {
    width: video.videoWidth,
    height: video.videoHeight,
    elapsedSeconds: Number(elapsed.toFixed(1)),
    presentedFps: Number(((after.totalVideoFrames - before.totalVideoFrames) / elapsed).toFixed(2)),
    droppedFps: Number(((after.droppedVideoFrames - before.droppedVideoFrames) / elapsed).toFixed(2)),
  };
}, seconds);
console.log(JSON.stringify({ file, ...result }));
await browser.close();