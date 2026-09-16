import { expect, test } from '@playwright/test';

const track = (index: number, streamIndex: number) => ({
  index, streamIndex, codec: 'aac', channels: 1, channelLayout: 'mono', sampleRate: 16000,
  language: 'eng', title: `Track ${index}`, sourceCodecBrowserCompatible: false,
  endpoint: `/api/v1/sources/source-a/audio-tracks/${index}/whep`,
});

const cameraSource = (id: string, name: string, cameraId: string) => ({
  id, kind: 'camera' as const, name, cameraId, profileId: 'main', hardwareDecode: 'auto',
  muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off' as const, audioTrack: 1, filters: [],
});

const scene = {
  schemaVersion: 5 as const, revision: 1, id: 'scene-1', name: 'Audio',
  canvas: { width: 1280, height: 720, backgroundColor: '#000000' },
  sources: [
    cameraSource('source-a', 'Camera A', 'cam-a'),
    cameraSource('source-b', 'Camera B', 'cam-b'),
    { id: 'source-c', kind: 'rtsp' as const, name: 'Stream C', rtspUrl: 'rtsp://127.0.0.1/live', transport: 'tcp',
      muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off' as const, audioTrack: 1, filters: [] },
  ],
  items: [0, 1, 2].map((index) => ({
    id: `item-${index}`, sourceId: ['source-a', 'source-b', 'source-c'][index], x: 0, y: 0, width: 640, height: 360,
    scaleMode: 'stretch' as const, crop: { top: 0, right: 0, bottom: 0, left: 0 }, zIndex: index,
    visible: true, locked: false, groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' as const,
  })),
};

const studio = { revision: 1, programSceneId: 'scene-1', previewSceneId: 'scene-1', scenes: [scene] };

test('audio workspace groups real tracks per source and wires per-track channels', async ({ page }) => {
  const posts: string[] = [];
  const deletes: string[] = [];
  const consoleErrors: string[] = [];
  page.on('pageerror', (error) => consoleErrors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  const gets: string[] = [];
  await page.route('**/api/v1/sources/**/audio-tracks', async (route) => {
    const url = route.request().url();
    gets.push(url);
    if (url.includes('source-a')) {
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ sourceId: 'source-a', probed: true, tracks: [track(0, 1), track(1, 2)] }) });
    }
    if (url.includes('source-b')) {
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ sourceId: 'source-b', probed: true, tracks: [] }) });
    }
    return route.fulfill({ status: 502, contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'audio_tracks_unavailable', message: 'probe failed' } }) });
  });
  await page.route('**/audio-tracks/*/whep**', async (route) => {
    const url = route.request().url();
    if (route.request().method() === 'DELETE') { deletes.push(url); return route.fulfill({ status: 204 }); }
    posts.push(url);
    const session = new URL(url).pathname.split('/whep')[0] + '/whep/session/' + 'a'.repeat(32);
    return route.fulfill({ status: 201, contentType: 'application/sdp',
      headers: { Location: session },
      body: 'v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=mid:0\r\na=recvonly\r\na=rtpmap:111 opus/48000/2\r\n' });
  });
  await page.goto('/');
  const result = await page.evaluate(async (studioDocument) => {
    const { mountAudioWorkspace } = await import('/tests/harness/audioWorkspaceMount.tsx');
    const host = document.createElement('div');
    document.body.appendChild(host);
    const workspace = mountAudioWorkspace(studioDocument as never, host);
    const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    const until = async (predicate: () => boolean, timeout = 4000) => {
      const started = Date.now();
      while (Date.now() - started < timeout) { if (predicate()) return true; await wait(60); }
      return predicate();
    };
    const channel = (sourceId: string) => Array.from(host.querySelectorAll('.audio-channel'))
      .find((node) => (node.textContent ?? '').includes(sourceId)) as HTMLElement | undefined;
    const loaded = await until(() => host.querySelectorAll('.audio-track').length >= 2);
    const names = Array.from(host.querySelectorAll('.audio-channel strong')).map((node) => node.textContent);
    const tracksA = Array.from(channel('Camera A')?.querySelectorAll('.audio-track') ?? []);
    const checkedA = tracksA.map((node) => (node.querySelector('input') as HTMLInputElement | null)?.checked);
    const controlsBefore = channel('Camera A')?.querySelectorAll('.audio-track-control').length;
    const meterBefore = channel('Camera A')?.querySelector('.vu-section')?.textContent ?? '';
    const modeButton = channel('Camera A')?.querySelector('.audio-level-mode') as HTMLButtonElement | null;
    const modeLabelBefore = modeButton?.textContent ?? '';
    modeButton?.click();
    await wait(120);
    const modeLabelAfter = (channel('Camera A')?.querySelector('.audio-level-mode') as HTMLButtonElement | null)?.textContent ?? '';
    // Enable the second track, then disable the first: the per-track channel must follow the selection.
    (tracksA[1]?.querySelector('input') as HTMLInputElement | undefined)?.click();
    await wait(300);
    const controlsAfter = channel('Camera A')?.querySelectorAll('.audio-track-control').length;
    (tracksA[0]?.querySelector('input') as HTMLInputElement | undefined)?.click();
    await wait(300);
    const controlsFinal = channel('Camera A')?.querySelectorAll('.audio-track-control').length;
    const noAudio = channel('Camera B')?.querySelector('.audio-track-missing')?.textContent ?? '';
    const unprobed = channel('Stream C')?.querySelector('.audio-track-missing')?.textContent ?? '';
    const reprobeButton = channel('Stream C')?.querySelector('.audio-track-missing button') as HTMLButtonElement | null;
    const reprobe = Boolean(reprobeButton);
    // "重新探测" must invalidate the cache instead of replaying the failure.
    reprobeButton?.click();
    await wait(400);
    const hiddenAudio = Array.from(document.querySelectorAll('audio[data-audio-track]')).length;
    workspace.unmount();
    return { names, loaded, checkedA, controlsBefore, meterBefore, modeLabelBefore, modeLabelAfter,
      controlsAfter, controlsFinal, noAudio, unprobed, reprobe, hiddenAudio,
      htmlSample: host.innerHTML.slice(0, 300) };
  }, studio);
  expect(result.names, `html=${result.htmlSample} console=${consoleErrors.join(' || ')}`).toEqual(['Camera A', 'Camera B', 'Stream C']);
  expect(result.loaded).toBe(true);
  // The first real track is selected by default; multi-select keeps the rest available.
  expect(result.checkedA).toEqual([true, false]);
  expect(result.controlsBefore).toBe(1);
  expect(result.meterBefore).toContain('合并');
  expect(result.modeLabelBefore).toContain('切换独立电平');
  expect(result.modeLabelAfter).toContain('切换合并电平');
  expect(result.controlsAfter).toBe(2);
  expect(result.controlsFinal).toBe(1);
  expect(result.noAudio).toContain('没有音频轨道');
  expect(result.unprobed).toContain('待探测');
  expect(result.reprobe).toBe(true);
  expect(gets.filter((url) => url.includes('source-c')).length).toBeGreaterThan(1);
  expect(posts.some((url) => url.includes('/source-a/audio-tracks/0/whep'))).toBe(true);
  expect(posts.some((url) => url.includes('/source-a/audio-tracks/1/whep'))).toBe(true);
  expect(deletes.some((url) => url.includes('/source-a/audio-tracks/0/whep/session/'))).toBe(true);
});
