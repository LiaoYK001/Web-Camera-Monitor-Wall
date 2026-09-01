import { useCallback, useEffect, useState } from 'react';
import {
  approveNodeEnrollment, createBackupJob, createClusterUser, createNodeEnrollment,
  fetchArchiveTargets, fetchBackupJobs, fetchClusterAudit, fetchClusterNodes, fetchClusterRecordingTimeline, fetchClusterRoles,
  fetchClusterUsers, fetchExternalProviders, fetchRecordingPlacements,
  fetchResourceCapacity, fetchStorageVolumes, fetchVerifiedArchivedRecording, patchClusterUser, patchStorageVolume,
  revokeClusterNode,
} from './api';
import type {
  ArchiveTarget, BackupJob, ClusterAuditRecord, ClusterNode, ClusterRecordingTimeline, ClusterRole, ClusterUser, ExternalProvider,
  RecordingPlacement, ResourceCapacity, StorageVolume,
} from './types';

const bytes = (value: number) => value >= 1024 ** 3
  ? `${(value / 1024 ** 3).toFixed(1)} GiB`
  : `${(value / 1024 ** 2).toFixed(1)} MiB`;
const time = (value: number) => value ? new Date(value * 1000).toLocaleString() : '—';
const timeMs = (value: number) => value ? new Date(value).toLocaleString() : '—';

function UserAccessEditor({ user, roles, onSaved, onError }: {
  user: ClusterUser;
  roles: Array<{ id: ClusterRole; permissions: string[] }>;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [selectedRoles, setSelectedRoles] = useState<ClusterRole[]>(user.roles);
  const [scopeText, setScopeText] = useState(user.scopes.map((scope) => `${scope.kind}:${scope.id}`).join(', '));
  const [saving, setSaving] = useState(false);
  const save = async () => {
    const scopes = scopeText.split(',').map((value) => value.trim()).filter(Boolean).map((value) => {
      const separator = value.indexOf(':');
      const kind = value.slice(0, separator);
      const id = value.slice(separator + 1);
      if (separator < 1 || !['camera', 'group'].includes(kind) || !/^[A-Za-z0-9._-]{1,64}$/.test(id)) {
        throw new Error('范围必须使用 camera:id 或 group:id，多个范围用逗号分隔。');
      }
      return { kind: kind as 'camera' | 'group', id };
    });
    if (!selectedRoles.length) throw new Error('用户至少需要一个角色。');
    setSaving(true);
    try {
      await patchClusterUser(user.id, user.revision, { roles: selectedRoles, scopes });
      await onSaved();
    } finally { setSaving(false); }
  };
  return <article className="user-access-card"><div><strong>{user.username}</strong><small>{user.enabled ? '已启用' : '已停用'} · revision {user.revision}</small></div>
    <fieldset><legend>角色</legend>{roles.map((role) => <label key={role.id} title={role.permissions.join(', ')}><input type="checkbox" checked={selectedRoles.includes(role.id)} onChange={() => setSelectedRoles((current) => current.includes(role.id) ? current.filter((item) => item !== role.id) : [...current, role.id])} />{role.id}</label>)}</fieldset>
    <label>Camera/Group 范围<input value={scopeText} placeholder="camera:front-door, group:office" onChange={(event) => setScopeText(event.target.value)} /></label>
    <div className="user-access-actions"><label><input type="checkbox" checked={user.enabled} onChange={() => void patchClusterUser(user.id, user.revision, { enabled: !user.enabled }).then(onSaved).catch((reason: Error) => onError(reason.message))} />启用</label><button type="button" disabled={saving || !selectedRoles.length} onClick={() => void save().catch((reason: Error) => onError(reason.message))}>{saving ? '保存中…' : '保存权限'}</button></div>
  </article>;
}

export default function ClusterAdmin() {
  const [users, setUsers] = useState<ClusterUser[]>([]);
  const [roles, setRoles] = useState<Array<{ id: ClusterRole; permissions: string[] }>>([]);
  const [auditRecords, setAuditRecords] = useState<ClusterAuditRecord[]>([]);
  const [nodes, setNodes] = useState<ClusterNode[]>([]);
  const [volumes, setVolumes] = useState<StorageVolume[]>([]);
  const [capacity, setCapacity] = useState<ResourceCapacity | null>(null);
  const [placements, setPlacements] = useState<RecordingPlacement[]>([]);
  const [recordingTimeline, setRecordingTimeline] = useState<ClusterRecordingTimeline | null>(null);
  const [archivePreview, setArchivePreview] = useState<{ segmentId: string; url: string } | null>(null);
  const [archiveLoading, setArchiveLoading] = useState('');
  const [targets, setTargets] = useState<ArchiveTarget[]>([]);
  const [jobs, setJobs] = useState<BackupJob[]>([]);
  const [providers, setProviders] = useState<ExternalProvider[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [newRole, setNewRole] = useState<ClusterRole>('viewer');
  const [nodeName, setNodeName] = useState('');
  const [nodeRole, setNodeRole] = useState<'recorder' | 'worker'>('recorder');
  const [enrollment, setEnrollment] = useState<{ id: string; token: string; expiresAt: number } | null>(null);

  const reload = useCallback(async (signal?: AbortSignal) => {
    try {
      const now = Date.now();
      const [nextUsers, nextRoles, nextAudit, nextNodes, nextVolumes, nextCapacity, nextPlacements,
        nextTimeline, nextTargets, nextJobs, nextProviders] = await Promise.all([
        fetchClusterUsers(signal), fetchClusterRoles(signal), fetchClusterAudit(32, undefined, signal), fetchClusterNodes(signal),
        fetchStorageVolumes(signal), fetchResourceCapacity(signal), fetchRecordingPlacements(signal),
        fetchClusterRecordingTimeline(now - 86_400_000, now, signal), fetchArchiveTargets(signal),
        fetchBackupJobs(signal), fetchExternalProviders(signal),
      ]);
      setUsers(nextUsers.users); setRoles(nextRoles.roles); setAuditRecords(nextAudit.records); setNodes(nextNodes.nodes);
      setVolumes(nextVolumes.volumes); setCapacity(nextCapacity); setPlacements(nextPlacements.placements);
      setRecordingTimeline(nextTimeline);
      setTargets(nextTargets.targets); setJobs(nextJobs.jobs); setProviders(nextProviders.providers);
      setError('');
    } catch (reason) {
      if (!signal?.aborted) setError(reason instanceof Error ? reason.message : '无法读取集群管理数据');
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, [reload]);

  useEffect(() => () => { if (archivePreview) URL.revokeObjectURL(archivePreview.url); }, [archivePreview]);

  const playArchived = async (segmentId: string, cameraId: string) => {
    setArchiveLoading(segmentId);
    try {
      const blob = await fetchVerifiedArchivedRecording(segmentId, cameraId);
      const url = URL.createObjectURL(blob);
      setArchivePreview((current) => {
        if (current) URL.revokeObjectURL(current.url);
        return { segmentId, url };
      });
      setNotice('归档录像已在浏览器本地完成大小与 SHA-256 校验。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '归档回放校验失败');
    } finally { setArchiveLoading(''); }
  };

  const addUser = async () => {
    try {
      await createClusterUser({ username: username.trim(), password, roles: [newRole], scopes: [] });
      setUsername(''); setPassword(''); setNotice('用户已创建；非管理员默认没有摄像机范围，需显式授权后才能访问媒体。');
      await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建用户失败'); }
  };

  const startEnrollment = async () => {
    try {
      const created = await createNodeEnrollment({ name: nodeName.trim(), role: nodeRole });
      setEnrollment(created); setNodeName('');
      setNotice('一次性令牌仅在当前页面显示；节点提交 CSR 后再执行批准。');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建节点注册失败'); }
  };

  return <main className="page-panel cluster-admin">
    <header className="page-heading"><div><span className="eyebrow">v2-M7 Operations</span><h1>集群、权限与灾备</h1><p>Standalone 保持默认；多节点操作全部由服务端 RBAC、mTLS、Revision 和租约再次校验。</p></div><button type="button" onClick={() => void reload()}>刷新</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {notice && <div className="capability-alert" role="status">{notice}</div>}

    <section className="admin-section"><header><div><h2>用户与 RBAC</h2><p>所有范围默认拒绝；管理员可再为用户配置 Camera/Group 范围。</p></div><span>{users.length} users</span></header>
      <div className="admin-form"><input aria-label="用户名" placeholder="用户名" value={username} maxLength={64} onChange={(event) => setUsername(event.target.value)} /><input aria-label="临时密码" placeholder="至少 16 字节临时密码" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /><select aria-label="角色" value={newRole} onChange={(event) => setNewRole(event.target.value as ClusterRole)}>{roles.map((role) => <option key={role.id} value={role.id}>{role.id}</option>)}</select><button type="button" disabled={username.trim().length < 3 || password.length < 16} onClick={() => void addUser()}>创建用户</button></div>
      <div className="admin-list">{users.map((user) => <UserAccessEditor key={`${user.id}:${user.revision}`} user={user} roles={roles} onSaved={() => reload()} onError={setError} />)}</div>
      <details><summary>最近 RBAC 审计（{auditRecords.length}）</summary><div className="admin-list">{auditRecords.map((record) => <article key={record.id}><div><strong>{record.event}</strong><small>{record.actorId} → {record.subjectId}<br />{time(record.createdAt)}</small></div><span>{record.result}</span></article>)}</div></details>
    </section>

    <section className="admin-section"><header><div><h2>节点与 mTLS</h2><p>注册令牌十分钟一次性；证书由节点本地私钥 CSR 签发并自动轮换。</p></div><span>{nodes.length} nodes</span></header>
      <div className="admin-form"><input aria-label="节点名称" placeholder="节点名称" value={nodeName} maxLength={64} onChange={(event) => setNodeName(event.target.value)} /><select aria-label="节点角色" value={nodeRole} onChange={(event) => setNodeRole(event.target.value as 'recorder' | 'worker')}><option value="recorder">recorder</option><option value="worker">worker</option></select><button type="button" disabled={!nodeName.trim()} onClick={() => void startEnrollment()}>生成注册令牌</button></div>
      {enrollment && <div className="one-time-secret"><strong>仅显示一次</strong><code>{enrollment.id}</code><code>{enrollment.token}</code><small>有效至 {time(enrollment.expiresAt)}</small><button type="button" onClick={() => void approveNodeEnrollment(enrollment.id).then(() => { setEnrollment(null); setNotice('节点 CSR 已批准。'); return reload(); }).catch((reason: Error) => setError(reason.message))}>批准已提交 CSR</button><button type="button" onClick={() => setEnrollment(null)}>隐藏令牌</button></div>}
      <div className="admin-grid">{nodes.map((node) => <article key={node.id}><header><strong>{node.name}</strong><span className={`health-dot ${node.status}`} />{node.status}</header><p>{node.role} · {node.version || '未报告版本'}</p><small>最近心跳 {time(node.lastSeenAt)}<br />证书到期 {time(node.certificateExpiresAt)}</small><button className="danger-button" type="button" onClick={() => { if (window.confirm('撤销此节点及其租约？')) void revokeClusterNode(node.id, node.revision).then(() => reload()).catch((reason: Error) => setError(reason.message)); }}>撤销节点</button></article>)}</div>
    </section>

    <section className="admin-section"><header><div><h2>存储卷与资源</h2><p>只能管理已挂载到 /recordings/volumes/&lt;volumeId&gt; 的卷。</p></div><span>{volumes.length} volumes</span></header>
      <div className="admin-grid">{volumes.map((volume) => { const used = volume.capacityBytes ? 1 - volume.freeBytes / volume.capacityBytes : 0; return <article key={`${volume.nodeId}/${volume.id}`}><header><strong>{volume.label}</strong><span>{volume.state}</span></header><p>{volume.tier} · {bytes(volume.freeBytes)} free / {bytes(volume.capacityBytes)}</p><progress value={Math.max(0, Math.min(1, used))} max={1} /><small>{Math.round(used * 100)}% used · high {Math.round(volume.highWatermark * 100)}%</small><select value={volume.state} onChange={(event) => void patchStorageVolume(volume, { state: event.target.value }).then(() => reload()).catch((reason: Error) => setError(reason.message))}><option value="online">online</option><option value="degraded">degraded</option><option value="read-only">read-only</option><option value="evacuating">evacuating</option><option value="offline">offline</option></select></article>; })}</div>
      <div className="admin-grid">{capacity?.nodes.map((node) => <article key={node.nodeId}><strong>节点资源 {node.nodeId.slice(0, 8)}</strong><p>{node.cpuCores} CPU · {bytes(node.memoryBytes)} RAM · {node.rated ? 'rated' : 'unrated/保守容量'}</p><small>{node.reservations.length} reservations · 更新 {time(node.updatedAt)}</small></article>)}</div>
      <details><summary>录像所有权租约（{placements.length}）</summary><div className="admin-list">{placements.map((item) => <article key={`${item.cameraId}/${item.profileId}`}><div><strong>{item.cameraId} / {item.profileId}</strong><small>node {item.nodeId.slice(0, 8)} · generation {item.generation}</small></div><span>{item.state}</span></article>)}</div></details>
      <details><summary>跨节点录像目录（{recordingTimeline?.cameras.reduce((count, camera) => count + camera.segments.length, 0) ?? 0}）</summary><div className="admin-list">{recordingTimeline?.cameras.flatMap((camera) => camera.segments).map((segment) => <article key={`${segment.id}:${segment.nodeId}:${segment.volumeId}`}><div><strong>{segment.cameraId} / {segment.profileId}</strong><small>{timeMs(segment.startUtcMs)} · {Math.round(segment.durationMs / 1000)} s · {bytes(segment.sizeBytes)}<br />node {segment.nodeId.slice(0, 8)} · volume {segment.volumeId} · {segment.videoCodec || 'codec —'}</small></div><span>{segment.integrity} · {segment.archiveState}</span>{segment.archiveState === 'uploaded' && ['verified', 'ok'].includes(segment.integrity) && <button type="button" disabled={archiveLoading === segment.id} onClick={() => void playArchived(segment.id, segment.cameraId)}>{archiveLoading === segment.id ? '下载校验中…' : '校验并回放'}</button>}</article>)}</div>{archivePreview && <article className="archive-verified-preview"><header><strong>已校验归档片段</strong><button type="button" onClick={() => setArchivePreview(null)}>关闭</button></header><video key={archivePreview.segmentId} src={archivePreview.url} controls playsInline preload="metadata" /></article>}</details>
    </section>

    <section className="admin-section"><header><div><h2>归档、备份与外部 Provider</h2><p>Secret 只以引用配置；UI 与 API 不返回凭据内容。</p></div><button type="button" onClick={() => void createBackupJob().then(() => { setNotice('本地加密备份已排队。'); return reload(); }).catch((reason: Error) => setError(reason.message))}>立即备份</button></header>
      <div className="admin-columns"><article><h3>S3 归档目标</h3>{targets.length ? targets.map((target) => <p key={target.id}><strong>{target.name}</strong><br /><small>{target.endpointAuthority} / {target.bucket} · {target.enabled ? '启用' : '停用'}</small></p>) : <p className="muted">未配置</p>}</article><article><h3>备份任务</h3>{jobs.slice(0, 8).map((job) => <p key={job.id}><strong>{job.state}</strong> · {time(job.createdAt)}<br /><small>{job.errorCode || (job.sha256 ? `SHA-256 ${job.sha256.slice(0, 12)}…` : '等待执行')}</small></p>)}</article><article><h3>外部 Provider</h3>{providers.length ? providers.map((provider) => <p key={provider.id}><strong>{provider.name}</strong><br /><small>{provider.taskTypes.join(', ')} · 并发 {provider.maxConcurrent}</small></p>) : <p className="muted">未配置</p>}</article></div>
    </section>
  </main>;
}
