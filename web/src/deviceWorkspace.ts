import type { StudioDocument } from './types';

/** Append a device collection to Preview with fresh IDs; leave the on-air graph intact. */
export function copyDeviceLayoutToPreview(server: StudioDocument, device: StudioDocument): StudioDocument {
  if (!device.scenes.length || server.scenes.length + device.scenes.length > 64)
    throw new Error('复制后会超过 64 个场景；请先减少设备布局或服务器中的场景。');
  const ids = new Map(device.scenes.map(scene => [scene.id, `scene-${crypto.randomUUID()}`]));
  const scenes = device.scenes.map(scene => {
    const sourceIds = new Map(scene.sources.map(source => [source.id, `source-${crypto.randomUUID()}`]));
    return { ...structuredClone(scene), id: ids.get(scene.id)!, revision: 1,
      name: `${scene.name.slice(0, 119)} · 设备布局`,
      sources: scene.sources.map(source => {
        if (source.kind === 'nested' && !ids.has(source.sceneId)) throw new Error('设备布局含缺失的嵌套场景，请先修复引用。');
        return { ...structuredClone(source), id: sourceIds.get(source.id)!,
          ...(source.kind === 'nested' ? { sceneId: ids.get(source.sceneId)! } : {}) };
      }),
      items: scene.items.map(item => ({ ...structuredClone(item), id: `item-${crypto.randomUUID()}`, sourceId: sourceIds.get(item.sourceId)! })),
    };
  });
  return { ...structuredClone(server), scenes: [...structuredClone(server.scenes), ...scenes],
    previewSceneId: ids.get(device.previewSceneId) ?? scenes[0].id };
}
