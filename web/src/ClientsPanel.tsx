import { useEffect, useState } from 'react';
import { approveClientEnrollment, fetchCameras, fetchClientEnrollments, fetchEnrolledClients, revokeEnrolledClient } from './api';
import type { CameraRecord, ClientCameraGrant, ClientEnrollment, ClientPermission, EnrolledClient } from './types';

const permissions: Array<{ id: ClientPermission; label: string }> = [
  { id: 'view', label: '观看' }, { id: 'snapshot', label: '截图' },
  { id: 'record-local', label: '本地录像' }, { id: 'ptz', label: 'PTZ' }, { id: 'talk', label: '对讲' },
];

type GrantDraft = ClientCameraGrant & { enabled: boolean };

const supportsManagedUsers = (camera: CameraRecord) => {
  const onvif = camera.capabilities.onvif;
  return camera.adapter === 'onvif' && typeof onvif === 'object' && onvif !== null &&
    (onvif as Record<string, unknown>).userManagement === true;
};

const freshGrant = (camera: CameraRecord): GrantDraft => ({
  cameraId: camera.id, profileIds: camera.profiles.map((profile) => profile.id),
  permissions: ['view'], credentialMode: 'existing', enabled: false,
});

export default function ClientsPanel({ onBack }: { onBack: () => void }) {
  const [enrollments, setEnrollments] = useState<ClientEnrollment[]>([]);
  const [clients, setClients] = useState<EnrolledClient[]>([]);
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, Record<string, GrantDraft>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const reload = async () => {
    try {
      const [pending, enrolled, registry] = await Promise.all([
        fetchClientEnrollments(), fetchEnrolledClients(), fetchCameras(),
      ]);
      setEnrollments(pending.enrollments);
      setClients(enrolled.clients);
      setCameras(registry.cameras);
      setDrafts((current) => {
        const next = { ...current };
        pending.enrollments.forEach((enrollment) => {
          next[enrollment.id] ??= Object.fromEntries(registry.cameras.map((camera) => [camera.id, freshGrant(camera)]));
        });
        return next;
      });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取本地客户端'); }
  };

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const updateGrant = (enrollmentId: string, cameraId: string, update: Partial<GrantDraft>) =>
    setDrafts((current) => ({ ...current, [enrollmentId]: {
      ...(current[enrollmentId] ?? {}),
      [cameraId]: { ...(current[enrollmentId]?.[cameraId] ?? freshGrant(cameras.find((item) => item.id === cameraId)!)), ...update },
    } }));

  const approve = async (enrollment: ClientEnrollment) => {
    const cameraGrants = Object.values(drafts[enrollment.id] ?? {}).filter((grant) => grant.enabled)
      .map(({ enabled: _enabled, ...grant }) => grant);
    if (!/^\d{8}$/.test(codes[enrollment.id] ?? '') || cameraGrants.length === 0 ||
        cameraGrants.some((grant) => grant.profileIds.length === 0 ||
          (grant.credentialMode === 'dedicated' && !grant.credentialsRef))) {
      setError('请输入客户端显示的八位配对码，并至少选择一个摄像机 Profile。'); return;
    }
    setBusy(true); setError(''); setNotice('');
    try {
      await approveClientEnrollment(enrollment.id, codes[enrollment.id], cameraGrants);
      setNotice(`已批准 ${enrollment.name}；设备将在下次轮询时取得加密授权包。`);
      await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '批准失败'); }
    finally { setBusy(false); }
  };

  return <main className="clients-page">
    <header className="registry-header"><div><span className="eyebrow">v2 True Direct</span><h1>本地客户端与授权</h1></div><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    <section className="client-section"><div className="section-title"><div><h2>待批准配对</h2><p>配对码十分钟有效。只授权实际需要的 Camera、Profile 和操作。</p></div><span>{enrollments.filter((item) => item.state === 'pending').length}</span></div>
      {enrollments.filter((item) => item.state === 'pending').length === 0 ? <div className="registry-empty">暂无待批准客户端</div> : enrollments.filter((item) => item.state === 'pending').map((enrollment) => <article className="enrollment-card" key={enrollment.id}>
        <header><div><strong>{enrollment.name}</strong><span>{enrollment.platform} · {Math.max(0, Math.ceil((enrollment.expiresAt * 1000 - Date.now()) / 60000))} 分钟后过期</span></div><label><span>配对码</span><input inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={codes[enrollment.id] ?? ''} onChange={(event) => setCodes((current) => ({ ...current, [enrollment.id]: event.target.value.replace(/\D/g, '') }))} /></label></header>
        <div className="grant-list">{cameras.map((camera) => {
          const grant = drafts[enrollment.id]?.[camera.id] ?? freshGrant(camera);
          return <div className={`grant-camera ${grant.enabled ? 'enabled' : ''}`} key={camera.id}>
            <label className="grant-title"><input type="checkbox" checked={grant.enabled} onChange={(event) => updateGrant(enrollment.id, camera.id, { enabled: event.target.checked })} /><strong>{camera.name}</strong><small>{camera.adapter}</small></label>
            {grant.enabled && <><div className="grant-options"><span>Profile</span>{camera.profiles.map((profile) => <label key={profile.id}><input type="checkbox" checked={grant.profileIds.includes(profile.id)} onChange={(event) => updateGrant(enrollment.id, camera.id, { profileIds: event.target.checked ? [...grant.profileIds, profile.id] : grant.profileIds.filter((id) => id !== profile.id) })} />{profile.role} · {profile.videoCodec || 'unknown'} {profile.width ? `${profile.width}×${profile.height}` : ''}</label>)}</div>
              <div className="grant-options"><span>权限</span>{permissions.map((permission) => <label key={permission.id}><input type="checkbox" disabled={permission.id === 'view'} checked={grant.permissions.includes(permission.id)} onChange={(event) => updateGrant(enrollment.id, camera.id, { permissions: event.target.checked ? [...grant.permissions, permission.id] : grant.permissions.filter((id) => id !== permission.id) })} />{permission.label}</label>)}</div>
              <label className="credential-mode"><span>凭据撤销</span><select value={grant.credentialMode} onChange={(event) => updateGrant(enrollment.id, camera.id, { credentialMode: event.target.value as 'existing' | 'dedicated', credentialsRef: undefined })}><option value="existing">复用现有 Secret（弱撤销）</option><option value="dedicated" disabled={!supportsManagedUsers(camera)}>ONVIF 托管专用账号</option></select></label>
              {grant.credentialMode === 'dedicated' && <label className="credential-mode"><span>专用 Secret 引用</span><input value={grant.credentialsRef ?? ''} maxLength={256} onChange={(event) => updateGrant(enrollment.id, camera.id, { credentialsRef: event.target.value.replace(/[^a-zA-Z0-9._/-]/g, '') })} /><small>Secret 用户名必须以 webobs- 开头，密码至少 16 字节；授权时创建账号，撤销时删除。</small></label>}</>}
          </div>;
        })}</div>
        <footer><span>完全离线设备最迟在 30 天 Grant 到期时失效；复用摄像机账号时，立即彻底撤销还需轮换摄像机密码。</span><button className="primary-button" disabled={busy} onClick={() => void approve(enrollment)}>批准并签发</button></footer>
      </article>)}
    </section>
    <section className="client-section"><div className="section-title"><h2>已配对设备</h2><span>{clients.length}</span></div>
      {clients.length === 0 ? <div className="registry-empty">尚无已配对设备</div> : <div className="client-list">{clients.map((client) => <article key={client.id}><div><strong>{client.name}</strong><span>{client.platform} · {client.cameraCount} 台摄像机</span></div><dl><div><dt>状态</dt><dd>{client.status}</dd></div><div><dt>最近在线</dt><dd>{new Date(client.lastSeen * 1000).toLocaleString()}</dd></div><div><dt>离线授权到期</dt><dd>{new Date(client.grantExpiresAt * 1000).toLocaleString()}</dd></div></dl>{client.weakRevocation && <p>⚠ 存在复用凭据或专用账号清理失败；彻底撤销可能还需轮换摄像机密码。</p>}<button className="danger-button" disabled={busy || client.status === 'revoked'} onClick={() => { if (window.confirm(`撤销 ${client.name}？在线播放与同步会在十秒内停止。`)) void revokeEnrolledClient(client.id).then((result) => { setNotice(result.weakRevocation ? `客户端已撤销，但摄像机凭据仍需人工轮换；现有 Grant 最迟于 ${new Date(result.offlineEffectiveNoLaterThan * 1000).toLocaleString()} 失效。` : '客户端已撤销，ONVIF 托管专用账号已清理。'); return reload(); }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '撤销失败')); }}>撤销</button></article>)}</div>}
    </section>
  </main>;
}
