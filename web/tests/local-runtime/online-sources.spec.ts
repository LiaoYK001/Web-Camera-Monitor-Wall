import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/auth/session') return route.fulfill({ json: { authenticated: true, user: 'website-fixture', via: 'session' } });
    if (url.pathname === '/api/v1/auth/setup') return route.fulfill({ json: { registrationOpen: false } });
    if (url.pathname === '/api/v1/runtime/info') return route.fulfill({ json: { platform: 'linux', go2rtcRtspBase: 'rtsp://127.0.0.1:28554/', onlineSourcesEnabled: true } });
    if (url.pathname === '/api/v1/go2rtc/api') return route.fulfill({ json: { version: '1.9.14' } });
    if (url.pathname === '/api/v1/go2rtc/api/streams') return route.fulfill({ json: {} });
    if (url.pathname === '/api/v1/go2rtc/api/config') return route.fulfill({ contentType: 'application/yaml', body: 'streams: {}' });
    if (url.pathname === '/api/v1/go2rtc/api/restart') return route.fulfill({ status: 202, json: {status: 'restarting'} });
    if (url.pathname === '/api/v1/cameras') return route.fulfill({ json: { cameras: [] } });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.route('**/api/v1/go2rtc/', route => route.fulfill({ contentType: 'text/html', body: '<h1>Isolated upstream UI</h1>' }));
});

test('website draft uses fixed encoded parameters, persists a named flow and refreshes imports', async ({ page }) => {
  let saved = '';
  await page.route('**/api/v1/go2rtc/api/config', route => {
    if (route.request().method() === 'PATCH') { saved = route.request().postDataJSON().streams['网页直播'][0]; return route.fulfill({ json: {} }); }
    return route.fulfill({ contentType: 'application/yaml', body: 'streams: {}' });
  });
  await page.route('**/api/v1/go2rtc/api/streams*', route => {
    return route.fulfill({ json: saved ? { '网页直播': {} } : {} });
  });
  await page.goto('/#/go2rtc');
  const form = page.getByRole('region', { name: '网站与直播源' });
  await form.getByLabel('流名称', { exact: true }).fill('网页直播');
  const address = 'https://example.test/视频?x=--output#chapter';
  await form.getByLabel('视频网页或直播地址').fill(address);
  await form.getByLabel('私密 Cookie 配置名（可选）').fill('my-account');
  await form.getByRole('button', { name: '保存命名流并重启 go2rtc' }).click();
  await expect(form.getByRole('status')).toContainText('已保存');
  const source = saved;
  expect(source).toContain('exec:webobs-online-source --engine yt-dlp');
  expect(source).toContain('--height 720 --video auto --cookies-name my-account --output {output}#starttimeout=90#killsignal=15');
  expect(Buffer.from(source.match(/--url64 ([\w-]+)/)![1], 'base64url').toString()).toBe(address);
  await expect(page.locator('.go2rtc-stream-list')).toContainText('网页直播');
  await expect(page.locator('.go2rtc-stream-list')).toContainText('rtsp://127.0.0.1:28554/');
});

test('existing names are refused before any mutation', async ({ page }) => {
  let writes = 0;
  await page.route('**/api/v1/go2rtc/api/config', route => { if (route.request().method() === 'PATCH') writes++; return route.fulfill({ contentType: 'application/yaml', body: 'streams: {}' }); });
  await page.route('**/api/v1/go2rtc/api/streams*', route => {
    return route.fulfill({ json: { existing: {} } });
  });
  await page.goto('/#/go2rtc');
  await page.getByLabel('流名称', { exact: true }).fill('existing');
  await page.getByLabel('视频网页或直播地址').fill('https://example.test/video');
  await page.getByRole('button', { name: '保存命名流并重启 go2rtc' }).click();
  await expect(page.getByRole('region', { name: '网站与直播源' }).getByRole('alert')).toContainText('已有同名流');
  expect(writes).toBe(0);
});

test('Windows removes POSIX signals and can choose Streamlink copy mode', async ({ page }) => {
  await page.route('**/api/v1/runtime/info', route => route.fulfill({ json: { platform: 'windows', go2rtcRtspBase: 'rtsp://127.0.0.1:28554/', onlineSourcesEnabled: true } }));
  let source = '';
  await page.route('**/api/v1/go2rtc/api/config', route => {
    if (route.request().method() === 'PATCH') { source = route.request().postDataJSON().streams.live[0]; return route.fulfill({ json: {} }); }
    return route.fulfill({ contentType: 'application/yaml', body: 'streams: {}' });
  });
  await page.route('**/api/v1/go2rtc/api/streams*', route => route.fulfill({ json: source ? { live: {} } : {} }));
  await page.goto('/#/go2rtc');
  await page.getByLabel('接入方式').selectOption('streamlink');
  await page.getByLabel('视频兼容策略').selectOption('copy');
  await page.getByLabel('流名称', { exact: true }).fill('live');
  await page.getByLabel('视频网页或直播地址').fill('https://example.test/live');
  await page.getByRole('button', { name: '保存命名流并重启 go2rtc' }).click();
  await expect(page.getByRole('region', { name: '网站与直播源' }).getByRole('status')).toContainText('已保存');
  expect(source).toContain('--engine streamlink'); expect(source).toContain('--video copy'); expect(source).not.toContain('killsignal');
});

test('old backends expose direct media and actionable upgrade instructions', async ({ page }) => {
  await page.route('**/api/v1/runtime/info', route => route.fulfill({ json: { platform: 'linux', go2rtcRtspBase: 'rtsp://127.0.0.1:18554/' } }));
  await page.goto('/#/go2rtc');
  await expect(page.getByLabel('接入方式')).toHaveValue('direct');
  await expect(page.getByRole('region', { name: '网站与直播源' })).toContainText('升级完整容器或 Windows x64');
  await expect(page.getByRole('button', { name: '保存命名流并重启 go2rtc' })).toBeEnabled();
});

test('permission failures hide the source form', async ({ page }) => {
  await page.route('**/api/v1/go2rtc/api', route => route.fulfill({ status: 403, json: {} }));
  await page.goto('/#/go2rtc');
  await expect(page.getByRole('alert')).toContainText('需要管理员');
  await expect(page.getByRole('region', { name: '网站与直播源' })).toHaveCount(0);
});

test('failed writes retain the draft and never announce success', async ({ page }) => {
  await page.route('**/api/v1/go2rtc/api/config', route => route.fulfill(route.request().method() === 'PATCH' ? { status: 503, json: {} } : { contentType: 'application/yaml', body: 'streams: {}' }));
  await page.goto('/#/go2rtc');
  await page.getByLabel('流名称', { exact: true }).fill('retry');
  await page.getByLabel('视频网页或直播地址').fill('https://example.test/video');
  await page.getByRole('button', { name: '保存命名流并重启 go2rtc' }).click();
  await expect(page.getByRole('region', { name: '网站与直播源' }).getByRole('alert')).toContainText('流未保存');
  await expect(page.getByLabel('流名称', { exact: true })).toHaveValue('retry');
});

test('a saved source with a rejected reload retains its draft and reports the failed restart', async ({page}) => {
  await page.route('**/api/v1/go2rtc/api/restart', route => route.fulfill({status: 503, json: {}}));
  await page.goto('/#/go2rtc');
  await page.getByLabel('流名称', {exact: true}).fill('retry-reload');
  await page.getByLabel('视频网页或直播地址').fill('https://example.test/video');
  await page.getByRole('button', {name: '保存命名流并重启 go2rtc'}).click();
  const form = page.getByRole('region', {name: '网站与直播源'});
  await expect(form.getByRole('alert')).toContainText('流已保存，但重载请求失败');
  await expect(form.getByLabel('流名称', {exact: true})).toHaveValue('retry-reload');
  await expect(form.getByRole('status')).toHaveCount(0);
});
