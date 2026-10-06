import { useEffect, useState } from 'react';
import { fetchStorageVolumes, patchStorageVolume } from './api';
import type { StorageVolume } from './types';
import type { ManagementActions } from './useManagementActions';

export default function StorageVolumeEditor({ volume, actions, onSaved, onRefresh, onDirty }: {
  volume: StorageVolume; actions: ManagementActions; onSaved: (volume: StorageVolume) => void;
  onRefresh: () => Promise<void>; onDirty: (key: string, dirty: boolean) => void;
}) {
  const key = 'volume:' + volume.nodeId + ':' + volume.id;
  const [baseline, setBaseline] = useState(volume), [draft, setDraft] = useState(volume.state);
  const state = actions.states[key], blocked = actions.blocked(key), dirty = draft !== baseline.state;
  const conflict = volume.revision !== baseline.revision || state?.phase === 'conflict';
  useEffect(() => { if (!dirty && !blocked && state?.phase !== 'conflict') { setBaseline(volume); setDraft(volume.state); } }, [volume]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { onDirty(key, dirty); return () => onDirty(key, false); }, [key, dirty, onDirty]);
  const save = async () => {
    if (blocked || conflict || !dirty) return;
    await actions.run(key, '修改存储卷', volume.nodeId + '/' + volume.id + ' · revision ' + baseline.revision,
      signal => patchStorageVolume(baseline, { state: draft }, signal),
      saved => { const next = { ...baseline, ...saved, state: draft }; onSaved(next); setBaseline(next); setDraft(next.state); });
    void onRefresh();
  };
  const reconcile = () => actions.reconcile(key, async signal => {
    const latest = (await fetchStorageVolumes(signal)).volumes.find(item => item.nodeId === volume.nodeId && item.id === volume.id);
    const resolved = Boolean(latest && latest.revision > baseline.revision && latest.state === draft);
    return { resolved, message: '存储卷状态尚不能确认此次修改；保留草稿与原 revision，未重发请求。',
      apply: () => { if (latest) { onSaved(latest); if (resolved) { setBaseline(latest); setDraft(latest.state); } } } };
  });
  return <div aria-label={'存储卷设置 ' + volume.label}>
    <label>状态<select disabled={blocked} value={draft} onChange={event => setDraft(event.target.value as StorageVolume['state'])}>
      {['online', 'degraded', 'read-only', 'evacuating', 'offline'].map(value => <option key={value} value={value}>{value}</option>)}
    </select></label><button type="button" disabled={blocked || conflict || !dirty} onClick={() => void save()}>保存存储卷</button>
    {conflict && <div role="alert">revision 冲突：服务器为 {volume.revision}，草稿基于 {baseline.revision}。草稿未被覆盖。
      <button type="button" disabled={blocked || volume.revision === baseline.revision} onClick={() => { setBaseline(volume); actions.clear(key); }}>保留草稿并采用新 revision</button>
      <button type="button" disabled={blocked} onClick={() => { setBaseline(volume); setDraft(volume.state); actions.clear(key); }}>放弃草稿并载入服务器值</button></div>}
    {state && <p role={state.phase === 'pending' ? 'status' : 'alert'}>{state.message}</p>}
    {state?.phase === 'unknown' && <button type="button" onClick={() => void reconcile()}>只读核对存储卷</button>}
  </div>;
}
