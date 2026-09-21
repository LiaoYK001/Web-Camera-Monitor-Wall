import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createLocalConfigBackup,
  deleteLocalConfigProfile,
  importLocalConfigBundle,
  listLocalConfigBackups,
  listLocalConfigProfiles,
  loadActiveLocalConfigProfile,
  makeLocalConfigBundle,
  restoreLocalConfigBackup,
  saveLocalConfigProfile,
  setActiveLocalConfigProfile,
  type LocalConfigBackup,
  type LocalConfigProfile,
} from './localRuntime';
import type { StudioDocument } from './types';

function fileName(name: string): string {
  const safe = name.trim().replace(/[^\p{L}\p{N}._-]+/gu, '-').slice(0, 48) || 'profile';
  return `webobs-config-${safe}-${new Date().toISOString().slice(0, 10)}.json`;
}

export default function ConfigProfiles({ studio, onProfileSelected }: {
  studio: StudioDocument | null;
  onProfileSelected?: (profile: LocalConfigProfile) => void;
}) {
  const [profiles, setProfiles] = useState<LocalConfigProfile[]>([]);
  const [backups, setBackups] = useState<LocalConfigBackup[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [name, setName] = useState('本机配置');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const importRef = useRef<HTMLInputElement>(null);

  const reload = async () => {
    const [nextProfiles, nextBackups, active] = await Promise.all([
      listLocalConfigProfiles(), listLocalConfigBackups(), loadActiveLocalConfigProfile(),
    ]);
    setProfiles(nextProfiles);
    setBackups(nextBackups);
    setSelectedId(active?.id ?? '');
    if (active) setName(active.name);
  };

  useEffect(() => {
    void reload().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法读取本机配置'));
    const changed = () => { void reload().catch(() => undefined); };
    window.addEventListener('webobs:config-profile-updated', changed);
    return () => window.removeEventListener('webobs:config-profile-updated', changed);
  }, []);

  const selected = useMemo(() => profiles.find((profile) => profile.id === selectedId) ?? null, [profiles, selectedId]);

  const selectProfile = async (id: string) => {
    setError(''); setNotice('');
    try {
      await setActiveLocalConfigProfile(id || null);
      if (!id) { setSelectedId(''); setNotice('已切回服务器默认配置。'); return; }
      const profile = profiles.find((candidate) => candidate.id === id);
      if (!profile) throw new Error('本机配置不存在');
      setSelectedId(id); setName(profile.name); onProfileSelected?.(profile);
      setNotice(`已载入“${profile.name}”；修改只保存在本机。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '载入本机配置失败'); }
  };

  const saveCurrent = async () => {
    if (!studio) { setError('当前还没有可保存的场景'); return; }
    try {
      const profile = await saveLocalConfigProfile(name, studio, selectedId || undefined);
      await setActiveLocalConfigProfile(profile.id);
      setSelectedId(profile.id); setName(profile.name); onProfileSelected?.(profile);
      setNotice(`已保存“${profile.name}”。`); setError(''); await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存本机配置失败'); }
  };

  const backup = async () => {
    if (!studio) { setError('当前还没有可备份的场景'); return; }
    try {
      const result = await createLocalConfigBackup(name, studio);
      setNotice(`已创建本机备份“${result.name}”。`); setError(''); await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建本机备份失败'); }
  };

  const exportSelected = () => {
    if (!selected) { setError('请先保存或选择一个本机配置'); return; }
    try {
      const blob = new Blob([JSON.stringify(makeLocalConfigBundle(selected), null, 2)], { type: 'application/json' });
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = fileName(selected.name);
      link.click(); URL.revokeObjectURL(link.href); setNotice('配置已导出（已脱敏）。'); setError('');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '导出配置失败'); }
  };

  const importFile = async (file?: File) => {
    if (!file) return;
    setError(''); setNotice('');
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('配置文件超过 2 MiB 限制');
      const profile = await importLocalConfigBundle(JSON.parse(await file.text()) as unknown);
      await setActiveLocalConfigProfile(profile.id); setSelectedId(profile.id); setName(profile.name); onProfileSelected?.(profile);
      setNotice(`已导入“${profile.name}”，并设为当前本机配置。`); await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '导入配置失败'); }
    finally { if (importRef.current) importRef.current.value = ''; }
  };

  const restore = async (id: string) => {
    try {
      const profile = await restoreLocalConfigBackup(id);
      if (!profile) throw new Error('本机备份不存在');
      setSelectedId(profile.id); setName(profile.name); onProfileSelected?.(profile);
      setNotice(`已恢复备份“${profile.name}”。`); setError(''); await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '恢复本机备份失败'); }
  };

  const remove = async () => {
    if (!selected || !window.confirm(`删除本机配置“${selected.name}”？不会删除服务器场景。`)) return;
    try { await deleteLocalConfigProfile(selected.id); setSelectedId(''); setNotice('本机配置已删除。'); setError(''); await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '删除本机配置失败'); }
  };

  return <article className="config-profile-panel">
    <header><div><h2>本机配置档案</h2><p>配置按浏览器本机选择，不按用户名区分。可保存多个布局并随时切换。</p></div><span className="config-profile-count">{profiles.length}/32</span></header>
    <div className="config-profile-controls">
      <label><span>当前档案</span><select value={selectedId} onChange={(event) => void selectProfile(event.target.value)}><option value="">服务器默认配置</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
      <label><span>名称</span><input value={name} maxLength={64} onChange={(event) => setName(event.target.value)} /></label>
      <button type="button" onClick={() => void saveCurrent()} disabled={!studio}>保存当前配置</button>
      <button type="button" onClick={() => void backup()} disabled={!studio}>立即备份</button>
      <button type="button" onClick={exportSelected} disabled={!selected}>导出 JSON</button>
      <button type="button" onClick={() => importRef.current?.click()}>导入 JSON</button>
      <button type="button" className="danger-button" onClick={() => void remove()} disabled={!selected}>删除档案</button>
      <input ref={importRef} className="visually-hidden" type="file" accept="application/json,.json" onChange={(event) => void importFile(event.target.files?.[0])} />
    </div>
    {error && <div className="alert" role="alert">{error}</div>}
    {notice && <p className="config-profile-notice" role="status">{notice}</p>}
    <p className="config-profile-safety">导出/备份只包含脱敏的 Scene v5、布局和本地偏好，不包含用户名、密码、Token、Secret、RTSP 地址或其他端点。数据使用本机 WebCrypto 加密保存。</p>
    {backups.length > 0 && <details className="config-backups"><summary>本机备份（{backups.length}）</summary>{backups.map((item) => <div key={item.id}><span><strong>{item.name}</strong><small>{new Date(item.createdAt).toLocaleString()}</small></span><button type="button" onClick={() => void restore(item.id)}>恢复</button></div>)}</details>}
  </article>;
}
