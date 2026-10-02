import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const base = process.env.WEBOBS_GO2RTC_TEST_ORIGIN;
assert(base, 'run this probe through tests/test_go2rtc_integration.py');
const browser = await chromium.launch();
try {
  const context = await browser.newContext();
  const login = await context.request.post(`${base}/api/v1/auth/login`, {
    headers: { Origin: base },
    data: { username: 'bridge-admin', password: process.env.WEBOBS_GO2RTC_TEST_PASSWORD },
  });
  assert.equal(login.status(), 200);
  const page = await context.newPage();
  const externalScripts = [];
  page.on('request', (request) => {
    if (request.resourceType() === 'script' && /^https?:/.test(request.url()) && !request.url().startsWith(base)) externalScripts.push(request.url());
  });
  await page.goto(`${base}/#/go2rtc`);
  await page.getByRole('heading', { name: 'go2rtc 管理' }).waitFor();
  const frame = page.frameLocator('iframe[title="go2rtc 官方 WebUI"]');
  await frame.getByRole('link', { name: 'config', exact: true }).waitFor();
  await page.getByRole('button', { name: '配置', exact: true }).click();
  await frame.locator('.monaco-editor').waitFor();
  await frame.getByRole('button', { name: 'Save & Restart' }).waitFor();
  assert.equal(externalScripts.length, 0, 'official editor attempted CDN scripts');
  const vendor = `${base}/api/v1/go2rtc/vendor/monaco-editor/`;
  const evidenceResponse = await context.request.get(`${vendor}webobs-sanitizer.json`);
  assert.equal(evidenceResponse.status(), 200);
  const evidence = await evidenceResponse.json();
  assert.equal(evidence.dompurifyVersion, '3.4.16');
  const actualSource = await (await context.request.get(`${vendor}${evidence.file}`)).body();
  assert.equal(createHash('sha256').update(actualSource).digest('hex'), evidence.packagedSha256);
  const sanitizerPage = await context.newPage();
  await sanitizerPage.goto(`${base}/api/v1/go2rtc/`);
  await sanitizerPage.addScriptTag({ url: `${base}/api/v1/go2rtc/vendor/dompurify/dist/purify.min.js` });
  const hooks = await sanitizerPage.evaluate(() => {
    const results = [];
    for (const hook of ['afterSanitizeElements', 'afterSanitizeAttributes']) {
      const purifier = window.DOMPurify(window);
      const root = document.createElement('div');
      root.innerHTML = '<section id="hook-fixture"><img src="data:," onerror="window.fixtureExecuted=true"></section>';
      const image = root.querySelector('img');
      document.body.append(root);
      purifier.addHook(hook, node => { if (node.id === 'hook-fixture') node.remove(); });
      purifier.sanitize(root, { IN_PLACE: true });
      results.push({ hook, version: purifier.version, armed: image.hasAttribute('onerror') });
      root.remove();
    }
    return results;
  });
  assert(hooks.every(result => result.version === '3.4.16' && !result.armed), JSON.stringify(hooks));
  await sanitizerPage.close();
  console.log('PASS: packaged sanitizer SHA-256 and afterSanitize detached-subtree XSS regressions');
  await page.screenshot({ path: '../tests/artifacts/go2rtc/workspace.png', fullPage: true });
  // MSE uses the real product WebSocket route and should display live frames.
  await page.goto(`${base}${'/api/v1/go2rtc/'}stream.html?src=synthetic&mode=mse`);
  await page.waitForFunction(() => {
    const video = document.querySelector('video-stream video');
    return video && video.readyState >= 2 && video.videoWidth > 0;
  }, undefined, { timeout: 15000 });
  console.log('PASS: real workspace iframe, local Monaco, CSP, MSE video frames');
} finally {
  await browser.close();
}
