import { useCallback, useEffect, useRef, useState } from 'react';
import UserAccessEditor from './UserAccessEditor';
import StorageVolumeEditor from './StorageVolumeEditor';
import { useManagementActions } from './useManagementActions';
import { managementRead, useManagementRefresh } from './useManagementRefresh';
import { useDraftGuard } from './useDraftGuard';
import { useDesktopWork } from './desktopRuntime';
import { useArchivedRecording } from './useArchivedRecording';
import {
  approveNodeEnrollment, createBackupJob, createClusterUser, createNodeEnrollment,
  fetchArchiveTargets, fetchBackupJobs, fetchClusterAudit, fetchClusterNodes, fetchClusterRecordingTimeline, fetchClusterRoles,
  fetchClusterUsers, fetchExternalProviders, fetchRecordingPlacements,
  fetchResourceCapacity, fetchStorageVolumes,
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

export default function ClusterAdmin() {
  const [users, setUsers] = useState<ClusterUser[]>([]);
  const [roles, setRoles] = useState<Array<{ id: ClusterRole; permissions: string[] }>>([]);
  const [auditRecords, setAuditRecords] = useState<ClusterAuditRecord[]>([]);
  const [nodes, setNodes] = useState<ClusterNode[]>([]);
  const [volumes, setVolumes] = useState<StorageVolume[]>([]);
  const [capacity, setCapacity] = useState<ResourceCapacity | null>(null);
  const [placements, setPlacements] = useState<RecordingPlacement[]>([]);
  const [recordingTimeline, setRecordingTimeline] = useState<ClusterRecordingTimeline | null>(null);
  const archive = useArchivedRecording();
  const [targets, setTargets] = useState<ArchiveTarget[]>([]);
  const [jobs, setJobs] = useState<BackupJob[]>([]);
  const [providers, setProviders] = useState<ExternalProvider[]>([]);
  const [notice, setNotice] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [newRole, setNewRole] = useState<ClusterRole>('viewer');
  const [nodeName, setNodeName] = useState('');
  const [nodeRole, setNodeRole] = useState<'recorder' | 'worker'>('recorder');
  const [enrollment, setEnrollment] = useState<{ id: string; token: string; expiresAt: number } | null>(null);

  const refresh = useManagementRefresh();
  const actions = useManagementActions(refresh.cancel);
  const [dirtyUsers, setDirtyUsers] = useState<Record<string, boolean>>({});
  const userDirty = useCallback((id: string, dirty: boolean) => setDirtyUsers(current => current[id] === dirty ? current : { ...current, [id]: dirty }), []);
  const userSaved = (user: ClusterUser) => setUsers(current => current.some(item => item.id === user.id) ? current.map(item => item.id === user.id ? user : item) : [...current, user]);
  const attempts = useRef<Record<string, { name?: string; target?: string; revision?: number; ids?: string[]; at: number }>>({});
  const dirty = Boolean(username || password || nodeName || enrollment || Object.values(dirtyUsers).some(Boolean) || actions.uncertain);
  useDesktopWork('cluster-management', dirty, actions.pending);
  useDraftGuard(dirty, actions.pending, '管理草稿、一次性令牌或未确认操作仅保存在本页。确定离开并丢弃这些信息吗？', setNotice);

  const reload = useCallback(async (signal?: AbortSignal) => {
    const now = Date.now();
    await refresh.run([
      managementRead('users', '用户', fetchClusterUsers, value => setUsers(value.users)),
      managementRead('roles', '角色', fetchClusterRoles, value => setRoles(value.roles)),
      managementRead('audit', '审计', signal => fetchClusterAudit(32, undefined, signal), value => setAuditRecords(value.records)),
      managementRead('nodes', '节点', fetchClusterNodes, value => setNodes(value.nodes)),
      managementRead('volumes', '存储卷', fetchStorageVolumes, value => setVolumes(value.volumes)),
      managementRead('capacity', '资源容量', fetchResourceCapacity, setCapacity),
      managementRead('placements', '录像放置', fetchRecordingPlacements, value => setPlacements(value.placements)),
      managementRead('timeline', '录像时间线', signal => fetchClusterRecordingTimeline(now - 86_400_000, now, signal), setRecordingTimeline),
      managementRead('targets', '归档目标', fetchArchiveTargets, value => setTargets(value.targets)),
      managementRead('jobs', '备份任务', fetchBackupJobs, value => setJobs(value.jobs)),
      managementRead('providers', '外部身份提供者', fetchExternalProviders, value => setProviders(value.providers)),
    ], signal);
  }, [refresh.run]);
  useEffect(() => { void reload(); }, [reload]);

  const addUser = async () => {
    const key = 'create-user';
    if (actions.blocked(key) || !username.trim() || password.length < 16) return;
    attempts.current[key] = { name: username.trim(), at: Date.now() };
    await actions.run(key, '创建用户', username.trim(), signal => createClusterUser({ username: username.trim(), password, roles: [newRole], scopes: [] }, signal),
      user => { userSaved(user); setUsername(''); setPassword(''); setNotice('用户已创建；非管理员默认没有摄像机范围，需显式授权后才能访问媒体。'); });
    void reload();
  };
  const startEnrollment = async () => {
    const key = 'create-enrollment';
    if (actions.blocked(key) || !nodeName.trim() || enrollment) return;
    attempts.current[key] = { name: nodeName.trim(), at: Date.now() };
    await actions.run(key, '创建节点注册', nodeName.trim(), signal => createNodeEnrollment({ name: nodeName.trim(), role: nodeRole }, signal),
      created => { setEnrollment(created); setNodeName(''); setNotice('一次性令牌仅在当前页面显示；节点提交 CSR 后再执行批准。'); });
  };
  const approveEnrollment = async () => {
    if (!enrollment || actions.blocked('approve-node:' + enrollment.id)) return;
    await actions.run('approve-node:' + enrollment.id, '批准节点', enrollment.id, signal => approveNodeEnrollment(enrollment.id, signal),
      () => { setEnrollment(null); setNotice('节点已批准。'); });
    void reload();
  };
  const revokeNode = async (node: ClusterNode) => {
    const key = 'node:' + node.id;
    if (actions.blocked(key) || actions.states[key]?.phase === 'conflict') return;
    await actions.run(key, '撤销节点', node.id + ' · revision ' + node.revision, signal => revokeClusterNode(node.id, node.revision, signal),
      () => { setNodes(current => current.map(item => item.id === node.id ? { ...item, status: 'revoked' } : item)); setNotice('节点已撤销。'); });
    void reload();
  };
  const backup = async () => {
    const key = 'backup:local';
    if (actions.blocked(key)) return;
    attempts.current[key] = { target: 'local', ids: jobs.map(job => job.id), at: Date.now() };
    await actions.run(key, '创建备份', 'local · ' + new Date(attempts.current[key].at).toLocaleString(), signal => createBackupJob('local', signal),
      job => { setJobs(current => [job, ...current.filter(item => item.id !== job.id)]); setNotice('备份任务已排队。'); });
    void reload();
  };
  const reconcile = (key: string) => actions.reconcile(key, async signal => {
    const attempt = attempts.current[key];
    if (key === 'create-user') {
      const value = await fetchClusterUsers(signal), found = value.users.find(user => user.username === attempt?.name);
      return { resolved: Boolean(found), message: '仍未查到该用户名；列表可能不完整或请求仍在执行，不能确认未创建。禁止重复提交。',
        apply: () => { setUsers(value.users); if (found) { setUsername(''); setPassword(''); setNotice('已查到该用户名；请核对其权限和密码状态，不会重发创建请求。'); } } };
    }
    if (key === 'backup:local') {
      const value = await fetchBackupJobs(signal), candidates = value.jobs.filter(job => job.targetId === attempt?.target && !attempt.ids?.includes(job.id));
      return { resolved: false, message: '备份结果仍未确认。新增候选任务：' + (candidates.map(job => job.id).join(', ') || '无') + '。服务端没有请求关联标识，不能证明是否由本次提交创建；请核对审计，勿重试。', apply: () => setJobs(value.jobs) };
    }
    const value = await fetchClusterNodes(signal);
    if (key.startsWith('node:')) return { resolved: value.nodes.some(node => node.id === key.slice(5) && node.status === 'revoked'), message: '节点撤销尚未确认，未重发请求。', apply: () => setNodes(value.nodes) };
    return { resolved: false, message: '节点列表已刷新，但注册令牌与批准操作没有可查询的请求关联标识。令牌不能恢复；请核对节点及审计，勿重复提交。', apply: () => setNodes(value.nodes) };
  });

  return <main className="page-panel cluster-admin">
    <header className="page-heading"><div><span className="eyebrow">v2-M7 Operations</span><h1>集群、权限与灾备</h1><p>Standalone 保持默认；多节点操作全部由服务端 RBAC、mTLS、Revision 和租约再次校验。</p></div><button type="button" onClick={() => void reload()}>刷新</button></header>
    {Object.entries(refresh.errors).map(([key, message]) => <div className="alert" role="alert" key={key}>{message}</div>)}
    {Object.entries(actions.states).filter(([key]) => !key.startsWith('user:') && !key.startsWith('volume:')).map(([key, state]) => <div key={key} role={state.phase === 'pending' ? 'status' : 'alert'}>
      {state.message} <small>{state.identity}</small>
      {state.phase === 'unknown' && <button type="button" onClick={() => void reconcile(key)}>只读核对结果</button>}
      {state.phase === 'conflict' && <button type="button" onClick={() => void reload().then(() => actions.clear(key))}>刷新并确认最新状态</button>}
    </div>)}
    {archive.error && <div className="alert" role="alert">{archive.error}</div>}
    {notice && <div className="capability-alert" role="status">{notice}</div>}

    <section className="admin-section"><header><div><h2>用户与 RBAC</h2><p>所有范围默认拒绝；管理员可再为用户配置 Camera/Group 范围。</p></div><span>{users.length} users</span></header>
      <div className="admin-form"><input aria-label="用户名" disabled={actions.blocked('create-user')} placeholder="用户名" value={username} maxLength={64} onChange={(event) => setUsername(event.target.value)} /><input aria-label="临时密码" disabled={actions.blocked('create-user')} placeholder="至少 16 字节临时密码" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /><select aria-label="角色" disabled={actions.blocked('create-user')} value={newRole} onChange={(event) => setNewRole(event.target.value as ClusterRole)}>{roles.map((role) => <option key={role.id} value={role.id}>{role.id}</option>)}</select><button type="button" disabled={actions.blocked('create-user') || username.trim().length < 3 || password.length < 16} onClick={() => void addUser()}>创建用户</button></div>
      <div className="admin-list">{users.map((user) => <UserAccessEditor key={user.id} user={user} roles={roles} actions={actions} onSaved={userSaved} onRefresh={reload} onDirty={userDirty} />)}</div>
      <details><summary>最近 RBAC 审计（{auditRecords.length}）</summary><div className="admin-list">{auditRecords.map((record) => <article key={record.id}><div><strong>{record.event}</strong><small>{record.actorId} → {record.subjectId}<br />{time(record.createdAt)}</small></div><span>{record.result}</span></article>)}</div></details>
    </section>

    <section className="admin-section"><header><div><h2>节点与 mTLS</h2><p>注册令牌十分钟一次性；证书由节点本地私钥 CSR 签发并自动轮换。</p></div><span>{nodes.length} nodes</span></header>
      <div className="admin-form"><input aria-label="节点名称" disabled={actions.blocked('create-enrollment')} placeholder="节点名称" value={nodeName} maxLength={64} onChange={(event) => setNodeName(event.target.value)} /><select aria-label="节点角色" disabled={actions.blocked('create-enrollment')} value={nodeRole} onChange={(event) => setNodeRole(event.target.value as 'recorder' | 'worker')}><option value="recorder">recorder</option><option value="worker">worker</option></select><button type="button" disabled={actions.blocked('create-enrollment') || Boolean(enrollment) || !nodeName.trim()} onClick={() => void startEnrollment()}>生成注册令牌</button></div>
      {enrollment && <div className="one-time-secret"><strong>仅显示一次</strong><code>{enrollment.id}</code><code>{enrollment.token}</code><small>有效至 {time(enrollment.expiresAt)}</small><button type="button" disabled={actions.blocked('approve-node:' + enrollment.id)} onClick={() => void approveEnrollment()}>批准已提交 CSR</button><button type="button" disabled={actions.blocked('approve-node:' + enrollment.id)} onClick={() => setEnrollment(null)}>隐藏令牌</button></div>}
      <div className="admin-grid">{nodes.map((node) => <article key={node.id}><header><strong>{node.name}</strong><span className={`health-dot ${node.status}`} />{node.status}</header><p>{node.role} · {node.version || '未报告版本'}</p><small>最近心跳 {time(node.lastSeenAt)}<br />证书到期 {time(node.certificateExpiresAt)}</small><button className="danger-button" type="button" disabled={actions.blocked('node:' + node.id) || actions.states['node:' + node.id]?.phase === 'conflict' || node.status === 'revoked'} onClick={() => { if (!actions.blocked('node:' + node.id) && window.confirm('撤销此节点及其租约？')) void revokeNode(node); }}>撤销节点</button></article>)}</div>
    </section>

    <section className="admin-section"><header><div><h2>存储卷与资源</h2><p>只能管理已挂载到 /recordings/volumes/&lt;volumeId&gt; 的卷。</p></div><span>{volumes.length} volumes</span></header>
      <div className="admin-grid">{volumes.map((volume) => { const used = volume.capacityBytes ? 1 - volume.freeBytes / volume.capacityBytes : 0; return <article key={`${volume.nodeId}/${volume.id}`}><header><strong>{volume.label}</strong><span>{volume.state}</span></header><p>{volume.tier} · {bytes(volume.freeBytes)} free / {bytes(volume.capacityBytes)}</p><progress value={Math.max(0, Math.min(1, used))} max={1} /><small>{Math.round(used * 100)}% used · high {Math.round(volume.highWatermark * 100)}%</small><StorageVolumeEditor volume={volume} actions={actions} onSaved={saved => setVolumes(current => current.map(item => item.nodeId === saved.nodeId && item.id === saved.id ? saved : item))} onRefresh={reload} onDirty={userDirty} /></article>; })}</div>
      <div className="admin-grid">{capacity?.nodes.map((node) => <article key={node.nodeId}><strong>节点资源 {node.nodeId.slice(0, 8)}</strong><p>{node.cpuCores} CPU · {bytes(node.memoryBytes)} RAM · {node.rated ? 'rated' : 'unrated/保守容量'}</p><small>{node.reservations.length} reservations · 更新 {time(node.updatedAt)}</small></article>)}</div>
      <details><summary>录像所有权租约（{placements.length}）</summary><div className="admin-list">{placements.map((item) => <article key={`${item.cameraId}/${item.profileId}`}><div><strong>{item.cameraId} / {item.profileId}</strong><small>node {item.nodeId.slice(0, 8)} · generation {item.generation}</small></div><span>{item.state}</span></article>)}</div></details>
      <details><summary>跨节点录像目录（{recordingTimeline?.cameras.reduce((count, camera) => count + camera.segments.length, 0) ?? 0}）</summary><div className="admin-list">{recordingTimeline?.cameras.flatMap((camera) => camera.segments).map((segment) => <article key={`${segment.id}:${segment.nodeId}:${segment.volumeId}`}><div><strong>{segment.cameraId} / {segment.profileId}</strong><small>{timeMs(segment.startUtcMs)} · {Math.round(segment.durationMs / 1000)} s · {bytes(segment.sizeBytes)}<br />node {segment.nodeId.slice(0, 8)} · volume {segment.volumeId} · {segment.videoCodec || 'codec —'}</small></div><span>{segment.integrity} · {segment.archiveState}</span>{segment.archiveState === 'uploaded' && ['verified', 'ok'].includes(segment.integrity) && <button type="button" disabled={archive.loading?.segmentId === segment.id && archive.loading.cameraId === segment.cameraId} onClick={() => void archive.select(segment.id, segment.cameraId)}>{archive.loading?.segmentId === segment.id && archive.loading.cameraId === segment.cameraId ? '下载校验中…' : '校验并回放'}</button>}</article>)}</div>{archive.busy && <button type="button" onClick={archive.close}>取消归档下载</button>}{archive.preview && <article className="archive-verified-preview"><header><strong>已校验归档片段</strong><button type="button" onClick={archive.close}>关闭</button></header><video key={archive.preview.url} src={archive.preview.url} controls playsInline preload="metadata" /></article>}</details>
    </section>

    <section className="admin-section"><header><div><h2>归档、备份与外部 Provider</h2><p>Secret 只以引用配置；UI 与 API 不返回凭据内容。</p></div><button type="button" disabled={actions.blocked('backup:local')} onClick={() => void backup()}>立即备份</button></header>
      <div className="admin-columns"><article><h3>S3 归档目标</h3>{targets.length ? targets.map((target) => <p key={target.id}><strong>{target.name}</strong><br /><small>{target.endpointAuthority} / {target.bucket} · {target.enabled ? '启用' : '停用'}</small></p>) : <p className="muted">未配置</p>}</article><article><h3>备份任务</h3>{jobs.slice(0, 8).map((job) => <p key={job.id}><strong>{job.state}</strong> · {time(job.createdAt)}<br /><small>{job.errorCode || (job.sha256 ? `SHA-256 ${job.sha256.slice(0, 12)}…` : '等待执行')}</small></p>)}</article><article><h3>外部 Provider</h3>{providers.length ? providers.map((provider) => <p key={provider.id}><strong>{provider.name}</strong><br /><small>{provider.taskTypes.join(', ')} · 并发 {provider.maxConcurrent}<br />待接收 {provider.taskCounts.offered ?? 0} · 媒体已打开 {provider.taskCounts['media-opened'] ?? 0} · 已过期 {provider.taskCounts.expired ?? 0}</small></p>) : <p className="muted">未配置</p>}</article></div>
    </section>
  </main>;
}
