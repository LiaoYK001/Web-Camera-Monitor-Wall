import { useEffect, useState } from 'react';
import { approveClientEnrollment, fetchCameras, fetchClientEnrollments, fetchEnrolledClients, revokeEnrolledClient } from './api';
import { beginBrowserEnrollment, completeBrowserEnrollment, currentBrowserPairing, type BrowserPairingState } from './browserEnrollment';
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

const isBrowserRuntime = (platform: ClientEnrollment['platform']) => platform === 'web' || platform === 'chromium-iwa';

const freshGrant = (camera: CameraRecord, platform: ClientEnrollment['platform']): GrantDraft => ({
  cameraId: camera.id, profileIds: camera.profiles.map((profile) => profile.id),
  permissions: ['view'], credentialMode: isBrowserRuntime(platform) ? 'none' : 'existing', enabled: false,
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
  const [browserName, setBrowserName] = useState('本机浏览器');
  const [browserPairing, setBrowserPairing] = useState<BrowserPairingState | null>(null);

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
          next[enrollment.id] ??= Object.fromEntries(registry.cameras.map((camera) => [camera.id, freshGrant(camera, enrollment.platform)]));
        });
        return next;
      });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取本地客户端'); }
  };

  useEffect(() => {
    void reload();
    void currentBrowserPairing().then(setBrowserPairing).catch(() => undefined);
    const timer = window.setInterval(() => void reload(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const updateGrant = (enrollment: ClientEnrollment, cameraId: string, update: Partial<GrantDraft>) =>
    setDrafts((current) => ({ ...current, [enrollment.id]: {
      ...(current[enrollment.id] ?? {}),
      [cameraId]: { ...(current[enrollment.id]?.[cameraId] ?? freshGrant(cameras.find((item) => item.id === cameraId)!, enrollment.platform)), ...update },
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

  const pairBrowser = async () => {
    setBusy(true); setError('');
    try {
      const state = await beginBrowserEnrollment(browserName);
      setBrowserPairing(state);
      setNotice('一次性配对身份只以加密形式保存在此 Origin 的 IndexedDB 中。');
      await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法创建浏览器配对'); }
    finally { setBusy(false); }
  };

  const finishBrowserPairing = async () => {
    setBusy(true); setError('');
    try {
      const state = await completeBrowserEnrollment();
      setBrowserPairing(state);
      setNotice(state?.state === 'approved' ? '此浏览器已取得签名、加密且不含摄像机凭据的 7 天授权。' : '管理员尚未批准此配对。');
      await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法完成浏览器配对'); }
    finally { setBusy(false); }
  };

  return <main className="clients-page">
    <header className="registry-header"><div><span className="eyebrow">v2 True Direct</span><h1>本地客户端与授权</h1></div><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    <section className="client-section"><div className="section-title"><div><h2>此浏览器</h2><p>PWA 使用 WebCrypto 包装密钥和本地打包的 libsodium；不会取得长期摄像机密码。</p></div><span>7 天</span></div>
      <div className="browser-pairing"><label><span>设备名称</span><input value={browserName} maxLength={64} onChange={(event) => setBrowserName(event.target.value)} /></label>
        {!browserPairing && <button className="primary-button" disabled={busy || !window.isSecureContext} onClick={() => void pairBrowser()}>创建浏览器配对</button>}
        {browserPairing?.state === 'pending' && <><strong>配对码：{browserPairing.pairingCode || '已创建'}</strong><span>请在下方待批准项输入该码并选择授权范围。</span><button className="primary-button" disabled={busy} onClick={() => void finishBrowserPairing()}>批准后完成配对</button></>}
        {browserPairing?.state === 'approved' && <strong>已配对 · 离线授权至 {new Date(browserPairing.expiresAt).toLocaleString()}</strong>}
        {!window.isSecureContext && <small>当前不是受信任 HTTPS Secure Context，浏览器配对已禁用。</small>}
      </div>
    </section>
    <section className="client-section"><div className="section-title"><div><h2>待批准配对</h2><p>配对码十分钟有效。只授权实际需要的 Camera、Profile 和操作。</p></div><span>{enrollments.filter((item) => item.state === 'pending').length}</span></div>
      {enrollments.filter((item) => item.state === 'pending').length === 0 ? <div className="registry-empty">暂无待批准客户端</div> : enrollments.filter((item) => item.state === 'pending').map((enrollment) => <article className="enrollment-card" key={enrollment.id}>
        <header><div><strong>{enrollment.name}</strong><span>{enrollment.platform} · {Math.max(0, Math.ceil((enrollment.expiresAt * 1000 - Date.now()) / 60000))} 分钟后过期</span></div><label><span>配对码</span><input inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={codes[enrollment.id] ?? ''} onChange={(event) => setCodes((current) => ({ ...current, [enrollment.id]: event.target.value.replace(/\D/g, '') }))} /></label></header>
        <div className="grant-list">{cameras.map((camera) => {
          const grant = drafts[enrollment.id]?.[camera.id] ?? freshGrant(camera, enrollment.platform);
          return <div className={`grant-camera ${grant.enabled ? 'enabled' : ''}`} key={camera.id}>
            <label className="grant-title"><input type="checkbox" checked={grant.enabled} onChange={(event) => updateGrant(enrollment, camera.id, { enabled: event.target.checked })} /><strong>{camera.name}</strong><small>{camera.adapter}</small></label>
            {grant.enabled && <><div className="grant-options"><span>Profile</span>{camera.profiles.map((profile) => <label key={profile.id}><input type="checkbox" checked={grant.profileIds.includes(profile.id)} onChange={(event) => updateGrant(enrollment, camera.id, { profileIds: event.target.checked ? [...grant.profileIds, profile.id] : grant.profileIds.filter((id) => id !== profile.id) })} />{profile.role} · {profile.videoCodec || 'unknown'} {profile.width ? `${profile.width}×${profile.height}` : ''}</label>)}</div>
              <div className="grant-options"><span>权限</span>{permissions.map((permission) => <label key={permission.id}><input type="checkbox" disabled={permission.id === 'view'} checked={grant.permissions.includes(permission.id)} onChange={(event) => updateGrant(enrollment, camera.id, { permissions: event.target.checked ? [...grant.permissions, permission.id] : grant.permissions.filter((id) => id !== permission.id) })} />{permission.label}</label>)}</div>
              {isBrowserRuntime(enrollment.platform)
                ? <p className="security-note">浏览器 Grant 不分发摄像机凭据，仅签发已通过 HTTPS/CORS 探测的非机密媒体端点。</p>
                : <label className="credential-mode"><span>凭据撤销</span><select value={grant.credentialMode} onChange={(event) => updateGrant(enrollment, camera.id, { credentialMode: event.target.value as 'existing' | 'dedicated', credentialsRef: undefined })}><option value="existing">复用现有 Secret（弱撤销）</option><option value="dedicated" disabled={!supportsManagedUsers(camera)}>ONVIF 托管专用账号</option></select></label>}
              {grant.credentialMode === 'dedicated' && <label className="credential-mode"><span>专用 Secret 引用</span><input value={grant.credentialsRef ?? ''} maxLength={256} onChange={(event) => updateGrant(enrollment, camera.id, { credentialsRef: event.target.value.replace(/[^a-zA-Z0-9._/-]/g, '') })} /><small>Secret 用户名必须以 webobs- 开头，密码至少 16 字节；授权时创建账号，撤销时删除。</small></label>}</>}
          </div>;
        })}</div>
        <footer><span>{isBrowserRuntime(enrollment.platform) ? '浏览器 Grant 最长离线 7 天且不包含摄像机凭据。' : '完全离线设备最迟在 30 天 Grant 到期时失效；复用摄像机账号时，立即彻底撤销还需轮换摄像机密码。'}</span><button className="primary-button" disabled={busy} onClick={() => void approve(enrollment)}>批准并签发</button></footer>
      </article>)}
    </section>
    <section className="client-section"><div className="section-title"><h2>已配对设备</h2><span>{clients.length}</span></div>
      {clients.length === 0 ? <div className="registry-empty">尚无已配对设备</div> : <div className="client-list">{clients.map((client) => <article key={client.id}><div><strong>{client.name}</strong><span>{client.platform} · {client.cameraCount} 台摄像机</span></div><dl><div><dt>状态</dt><dd>{client.status}</dd></div><div><dt>最近在线</dt><dd>{new Date(client.lastSeen * 1000).toLocaleString()}</dd></div><div><dt>离线授权到期</dt><dd>{new Date(client.grantExpiresAt * 1000).toLocaleString()}</dd></div></dl>{client.weakRevocation && <p>⚠ 存在复用凭据或专用账号清理失败；彻底撤销可能还需轮换摄像机密码。</p>}<button className="danger-button" disabled={busy || client.status === 'revoked'} onClick={() => { if (window.confirm(`撤销 ${client.name}？在线播放与同步会在十秒内停止。`)) void revokeEnrolledClient(client.id).then((result) => { setNotice(result.weakRevocation ? `客户端已撤销，但摄像机凭据仍需人工轮换；现有 Grant 最迟于 ${new Date(result.offlineEffectiveNoLaterThan * 1000).toLocaleString()} 失效。` : '客户端已撤销，ONVIF 托管专用账号已清理。'); return reload(); }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '撤销失败')); }}>撤销</button></article>)}</div>}
    </section>
  </main>;
}
