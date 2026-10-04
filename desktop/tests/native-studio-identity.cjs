// Real authenticated APIs in an isolated test profile; no camera/media mocks.
const assert = require('node:assert/strict');

exports.exerciseStudioIdentity = async (origin, headers, observe = async () => {}, request = fetch) => {
  const read = async path => {
    const response = await request(origin + path, { headers });
    assert.equal(response.status, 200); return response.json();
  };
  const write = async (path, body, method = 'PUT', revision) => {
    const response = await request(origin + path, { method, headers: { ...headers,
      'Content-Type': 'application/json', ...(revision === undefined ? {} : { 'If-Match': `"${revision}"` }) },
      body: body === undefined ? undefined : JSON.stringify(body) });
    assert.equal(response.status, 200, `isolated identity fixture ${path}`); return response.json();
  };
  const studioPath = '/api/v1/studio', preferencePath = '/api/v2/account/preferences/monitor-view';
  const originalStudio = await read(studioPath);
  const originalPreferences = (await read(preferencePath)).value ?? {};
  const source = (suffix, name) => ({ id: `camera-00000000-0000-4000-8000-00000000000${suffix}`,
    name, kind: 'color', color: '#214f75', muted: true, volume: 1, syncOffsetMs: 0,
    monitoring: 'off', audioTrack: 1, audioInputs: [], filters: [] });
  const item = (suffix, sourceId, x, zIndex) => ({ id: `item-00000000-0000-4000-8000-00000000000${suffix}`,
    sourceId, x, y: 0, width: 640, height: 360, zIndex, visible: true, locked: false,
    scaleMode: 'contain', crop: { top: 0, right: 0, bottom: 0, left: 0 },
    groupId: '', rotation: 0, opacity: 1, blendMode: 'normal' });
  const a = { ...structuredClone(originalStudio.scenes[0]),
    id: 'scene-00000000-0000-4000-8000-000000000001', name: 'Identity Scene A', revision: 0,
    sources: [source(1, 'Identity A'), source(2, 'Identity B')] };
  a.items = a.sources.map((value, index) => item(index + 1, value.id, index * 640, index));
  const b = { ...structuredClone(a), id: 'scene-00000000-0000-4000-8000-000000000002', name: 'Identity Scene B' };
  b.sources[0].name = 'Identity C'; b.sources[1].name = 'Identity D';
  const child = { ...structuredClone(a), id: 'identity-child', name: 'Identity child',
    sources: [{ ...source(1, 'Identity Shared'), id: 'shared' }] };
  child.items = [item(1, 'shared', 0, 0)];
  const nested = { ...structuredClone(a), id: 'identity-nested', name: 'Identity repeated nested',
    sources: [{ id: 'nested', name: 'Child', kind: 'nested', sceneId: child.id,
      muted: true, volume: 1, syncOffsetMs: 0, monitoring: 'off', audioTrack: 1, filters: [] }],
    items: [item(1, 'nested', 0, 0), item(2, 'nested', 640, 1)] };
  const fixture = { ...structuredClone(originalStudio), scenes: [...originalStudio.scenes, a, b, child, nested] };
  const activate = async id => {
    fixture.previewSceneId = id;
    const current = await read(studioPath);
    fixture.revision = current.revision;
    const saved = await write(studioPath, fixture, 'PUT', current.revision);
    await write('/api/v1/studio/take', undefined, 'POST', saved.revision);
    return read('/api/v1/scene');
  };
  const ids = value => Object.fromEntries(value.sources.map(entry => [entry.name, entry.id]));
  const items = value => Object.fromEntries(value.items.map(entry => [entry.x, entry.id]));
  const restore = async () => {
    const current = await read(studioPath);
    const saved = await write(studioPath, { ...originalStudio, revision: current.revision }, 'PUT', current.revision);
    await write('/api/v1/studio/take', undefined, 'POST', saved.revision);
    await write(preferencePath, { value: originalPreferences });
  };
  try {
    const initial = await activate(a.id);
    const aIds = ids(initial), aItems = items(initial);
    assert.equal(new Set(Object.values(aIds)).size, 2);
    for (const id of Object.values(aIds)) assert.ok(id.length <= 64 && !/^source-\d+$/.test(id));
    const controls = { 'Identity A': { volume: .27, muted: false, monitor: false },
      'Identity B': { volume: .63, muted: true, monitor: true } };
    const value = { localMonitorVolume: .18, mode: 'manual', showAllAudioSources: true,
      sourceAudio: { ...Object.fromEntries(Object.entries(aIds).map(([name, id]) => [id, controls[name]])),
        'source-0': { volume: .99, muted: false, monitor: true } },
      sourceDecorations: Object.fromEntries(Object.values(aIds).map(id => [id, { fill: 'contain' }])) };
    await write(preferencePath, { value });
    await observe(initial, controls);
    [a.items[0].zIndex, a.items[1].zIndex] = [a.items[1].zIndex, a.items[0].zIndex];
    const reordered = await activate(a.id);
    assert.deepEqual(ids(reordered), aIds); assert.deepEqual(items(reordered), aItems);
    await observe(reordered, controls);
    const other = await activate(b.id), bIds = ids(other);
    assert.ok(Object.values(bIds).every(id => !Object.values(aIds).includes(id)));
    await observe(other, { 'Identity C': { volume: 1, muted: true, monitor: true },
      'Identity D': { volume: 1, muted: true, monitor: true } });
    const back = await activate(a.id);
    assert.deepEqual(ids(back), aIds); await observe(back, controls);
    assert.deepEqual((await read(preferencePath)).value, value, 'Scene changes must not migrate ambiguous legacy controls');
    const repeated = await activate(nested.id);
    assert.equal(repeated.sources.length, 1); assert.equal(repeated.items.length, 2);
    assert.notEqual(repeated.items[0].id, repeated.items[1].id);
    const repeatItems = items(repeated), sharedId = repeated.sources[0].id;
    [nested.items[0].zIndex, nested.items[1].zIndex] = [nested.items[1].zIndex, nested.items[0].zIndex];
    const repeatedAgain = await activate(nested.id);
    assert.deepEqual(items(repeatedAgain), repeatItems); assert.equal(repeatedAgain.sources[0].id, sharedId);
    await observe(repeatedAgain, { 'Identity Shared': { volume: 1, muted: true, monitor: true } });
    console.log('Actual authenticated Studio TAKE: UUID source/item identities survive layer changes and Scene switches; repeated nested instances have distinct items and one shared source; account controls and ambiguous legacy records remain intact. Synthetic color controls only.');
    return async (restarted = false) => {
      const persisted = await read('/api/v1/scene');
      assert.deepEqual(ids(persisted), ids(repeatedAgain)); assert.deepEqual(items(persisted), repeatItems);
      assert.deepEqual((await read(preferencePath)).value, value);
      await observe(persisted, { 'Identity Shared': { volume: 1, muted: true, monitor: true } });
      const restored = await activate(a.id);
      assert.deepEqual(ids(restored), aIds); await observe(restored, controls);
      console.log(restarted
        ? 'Actual normal service restart: frozen Program, nested identities and per-Scene account controls persist; switching back restores each source control.'
        : 'Actual account reread and return to Scene A retain source identities and independent monitor controls.');
      await restore();
    };
  } catch (error) { await restore().catch(() => {}); throw error; }
};
