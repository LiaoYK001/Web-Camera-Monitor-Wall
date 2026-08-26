import { expect, test } from '@playwright/test';

// Media runtime security contracts: WHEP session Location compatibility and
// HLS child-resource/cookie isolation. Runs against the Vite dev server, which
// serves the real /src modules.

test('WHEP session Location accepts both direct and session-prefixed formats', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const { validSessionLocation } = await import('/src/whep.ts');
    const base = 'https://media.example:8443/api/v2/media-plans/0123456789abcdef0123456789abcdef/whep';
    const endpoint = new URL(base);
    const direct = validSessionLocation(`${base}/abc_123-xyz.~`, endpoint);
    const prefixed = validSessionLocation(`${base}/session/abc_123-xyz.~`, endpoint);
    const crossOrigin = validSessionLocation('https://evil.example/whep/abc', endpoint);
    const withQuery = validSessionLocation(`${base}/abc?token=1`, endpoint);
    const traversal = validSessionLocation(`${base}/../other/abc`, endpoint);
    return { direct, prefixed, crossOrigin, withQuery, traversal };
  });
  expect(result.direct).toBe(`${'https://media.example:8443/api/v2/media-plans/0123456789abcdef0123456789abcdef/whep'}/abc_123-xyz.~`);
  expect(result.prefixed).toBe(`${'https://media.example:8443/api/v2/media-plans/0123456789abcdef0123456789abcdef/whep'}/session/abc_123-xyz.~`);
  expect(result.crossOrigin).toBeNull();
  expect(result.withQuery).toBeNull();
  expect(result.traversal).toBeNull();
});

test('HLS child resources stay same-origin HTTPS and disable cookies', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const { validateHlsChildUrl, hlsXhrSetup } = await import('/src/browserMedia.ts');
    const base = new URL('https://media.example:8443/live/index.m3u8');
    const attempt = (child: string): boolean => {
      try { validateHlsChildUrl(child, base); return true; } catch { return false; }
    };
    const sameOrigin = attempt('https://media.example:8443/live/seg0.m4s');
    const crossOrigin = attempt('https://evil.example/live/seg0.m4s');
    const insecure = attempt('http://media.example:8443/live/seg0.m4s');
    const credential = attempt('https://user:pass@media.example:8443/live/seg0.m4s');
    const xhr = { withCredentials: true } as XMLHttpRequest;
    hlsXhrSetup(xhr, 'https://media.example:8443/live/seg0.m4s', base);
    return { sameOrigin, crossOrigin, insecure, credential, withCredentials: xhr.withCredentials };
  });
  expect(result.sameOrigin).toBe(true);
  expect(result.crossOrigin).toBe(false);
  expect(result.insecure).toBe(false);
  expect(result.credential).toBe(false);
  expect(result.withCredentials).toBe(false);
});
