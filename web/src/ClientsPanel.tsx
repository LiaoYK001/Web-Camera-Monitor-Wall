import { useCallback, useEffect, useRef, useState } from 'react';
import { useManagementActions } from './useManagementActions';
import { managementRead, useManagementRefresh } from './useManagementRefresh';
import { useDesktopWork } from './desktopRuntime';
import { useDraftGuard } from './useDraftGuard';
import { canLeaveWorkspace } from './navigationGuard';
import { useVisiblePolling } from './useVisiblePolling';
import { approveClientEnrollment, fetchCameras, fetchClientEnrollments, fetchEnrolledClients, revokeEnrolledClient } from './api';
import { beginBrowserEnrollment, completeBrowserEnrollment, currentBrowserPairing, type BrowserPairingState } from './browserEnrollment';
import type { CameraRecord, ClientCameraGrant, ClientEnrollment, ClientPermission, EnrolledClient } from './types';

const permissions: Array<{ id: ClientPermission; label: string }> = [
  { id: 'view', label: '观看' }, { id: 'snapshot', label: '截图' },
  { id: 'record-local', label: '本地录像' }, { id: 'ptz', label: 'PTZ' }, { id: 'talk', label: '对讲' },
];

type GrantDraft = ClientCameraGrant & { enabled: boolean };
// Server rows plus a page-local marker: an enrollment that disappeared from the
// latest read while this page still holds a draft for it. Never sent to the API.
type EnrollmentRow = ClientEnrollment & { stale?: boolean };

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
  const [enrollments, setEnrollments] = useState<EnrollmentRow[]>([]);
  const [clients, setClients] = useState<EnrolledClient[]>([]);
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [updateTargets, setUpdateTargets] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, Record<string, GrantDraft>>>({});
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [browserName, setBrowserName] = useState('本机浏览器');
  const [browserPairing, setBrowserPairing] = useState<BrowserPairingState | null>(null);
  const refresh = useManagementRefresh();
  const actions = useManagementActions(refresh.cancel);
  const [edited, setEdited] = useState<Record<string, boolean>>({});
  const attempts = useRef<Record<string, { enrollmentId: string; target?: string }>>({});
  const dirty = Object.values(edited).some(Boolean) || actions.uncertain || browserName !== '本机浏览器';
  useDesktopWork('client-management', dirty, actions.pending);
  useDraftGuard(dirty, actions.pending, '客户端授权草稿或未确认操作仅保存在本页。确定离开吗？', setNotice);
  const read = useCallback(async (signal: AbortSignal) => {
    await refresh.run([
      managementRead('enrollments', '待批准配对', fetchClientEnrollments, value => setEnrollments(current => {
        // Keep disappeared drafts addressable, but never submit a missing/expired enrollment.
        const ids = new Set(value.enrollments.map(item => item.id));
        return [...value.enrollments, ...current.filter(item => !ids.has(item.id)).map(item => ({ ...item, stale: true }))];
      })),
      managementRead('clients', '已配对设备', fetchEnrolledClients, value => setClients(value.clients)),
      managementRead('cameras', '摄像机目录', fetchCameras, value => setCameras(value.cameras)),
    ], signal);
  }, [refresh.run]);
  const polling = useVisiblePolling(read, 5000);
  useEffect(() => {
    setDrafts(current => {
      const next = { ...current };
      enrollments.forEach(enrollment => { next[enrollment.id] ??= {}; cameras.forEach(camera => {
        next[enrollment.id] = { ...next[enrollment.id], [camera.id]: next[enrollment.id][camera.id] ?? freshGrant(camera, enrollment.platform) };
      }); });
      return next;
    });
  }, [enrollments, cameras]);
  const enrollmentKey = (id: string) => 'approve-client:' + id;
  const enrollmentBlocked = (id: string) => actions.blocked(enrollmentKey(id)) || Boolean(updateTargets[id] && actions.blocked('client:' + updateTargets[id]));
  const clearDraft = (id: string) => {
    setEdited(current => ({ ...current, [id]: false }));
    setCodes(current => ({ ...current, [id]: '' }));
    setUpdateTargets(current => ({ ...current, [id]: '' }));
    setDrafts(current => { const next = { ...current }; delete next[id]; return next; });
  };

  useEffect(() => {
    let active = true;
    void currentBrowserPairing().then((value) => { if (active) setBrowserPairing(value); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  const updateGrant = (enrollment: EnrollmentRow, cameraId: string, update: Partial<GrantDraft>) => {
    if (enrollmentBlocked(enrollment.id)) return;
    setEdited(current => ({ ...current, [enrollment.id]: true }));
    setDrafts((current) => ({ ...current, [enrollment.id]: {
      ...(current[enrollment.id] ?? {}),
      [cameraId]: { ...(current[enrollment.id]?.[cameraId] ?? freshGrant(cameras.find((item) => item.id === cameraId)!, enrollment.platform)), ...update },
    } }));
  };

  const approve = async (enrollment: EnrollmentRow) => {
    const key = enrollmentKey(enrollment.id), target = updateTargets[enrollment.id] || undefined;
    if (enrollmentBlocked(enrollment.id) || enrollment.state !== 'pending' || enrollment.stale || actions.states[key]?.phase === 'conflict') return;
    const cameraGrants = Object.values(drafts[enrollment.id] ?? {}).filter(grant => grant.enabled).map(({ enabled: _enabled, ...grant }) => grant);
    if (!/^\d{8}$/.test(codes[enrollment.id] ?? '') || !cameraGrants.length || cameraGrants.some(grant =>
      !grant.profileIds.length || (grant.credentialMode === 'dedicated' && !grant.credentialsRef) ||
      !cameras.some(camera => camera.id === grant.cameraId && grant.profileIds.every(id => camera.profiles.some(profile => profile.id === id)))) ||
      (target && !clients.some(client => client.id === target && client.status === 'active' && client.platform === enrollment.platform))) {
      setError('请输入八位配对码，并核对摄像机 Profile 与目标设备；目录变更不会自动修改草稿。'); return;
    }
    attempts.current[key] = { enrollmentId: enrollment.id, target };
    setError('');
    await actions.run(key, '批准并签发', enrollment.id + (target ? ' → ' + target : ''),
      signal => approveClientEnrollment(enrollment.id, codes[enrollment.id], cameraGrants, target, signal),
      result => { clearDraft(enrollment.id); setEnrollments(current => current.map(item => item.id === enrollment.id ? { ...item, state: 'approved' } : item));
        setNotice(result.updated ? '设备授权已更新；旧设备令牌已失效。' : '已批准；设备将在下次轮询时取得加密授权包。'); }, target ? ['client:' + target] : []);
    void polling.refresh();
  };
  const pairBrowser = async () => {
    await actions.run('browser-pairing', '创建浏览器配对', browserName, () => beginBrowserEnrollment(browserName),
      state => { setBrowserPairing(state); setNotice('一次性配对身份只以加密形式保存在此 Origin 的 IndexedDB 中。'); });
    void polling.refresh();
  };
  const finishBrowserPairing = async () => {
    await actions.run('browser-pairing', '完成浏览器配对', browserName, () => completeBrowserEnrollment(),
      state => { setBrowserPairing(state); setNotice(state?.state === 'approved' ? '此浏览器已取得签名、加密且不含摄像机凭据的 7 天授权。' : '管理员尚未批准此配对。'); });
    void polling.refresh();
  };
  const revoke = async (client: EnrolledClient) => {
    const key = 'client:' + client.id;
    if (actions.blocked(key) || client.status === 'revoked' || !window.confirm('撤销 ' + client.name + '？在线播放与同步会在十秒内停止。')) return;
    await actions.run(key, '撤销客户端', client.id, signal => revokeEnrolledClient(client.id, signal),
      result => { setClients(current => current.map(item => item.id === client.id ? { ...item, status: 'revoked' } : item));
        setNotice(result.weakRevocation ? '客户端已撤销，但摄像机凭据仍需人工轮换；现有 Grant 最迟于 ' + new Date(result.offlineEffectiveNoLaterThan * 1000).toLocaleString() + ' 失效。' : '客户端已撤销，ONVIF 托管专用账号已清理。'); });
    void polling.refresh();
  };
  const reconcile = (key: string) => actions.reconcile(key, async signal => {
    if (key === 'browser-pairing') {
      const state = await currentBrowserPairing();
      return { resolved: Boolean(state), message: '浏览器配对仍未确认；不要重复创建，稍后只读核对。', apply: () => { if (state) setBrowserPairing(state); } };
    }
    if (key.startsWith('approve-client:')) {
      const value = await fetchClientEnrollments(signal), attempt = attempts.current[key];
      const found = value.enrollments.find(item => item.id === attempt?.enrollmentId), resolved = found?.state === 'approved';
      return { resolved, message: '批准结果尚未确认；没有返回 approved 的相同 enrollment，未重发授权请求。',
        apply: () => { if (found) setEnrollments(current => current.map(item => item.id === found.id ? found : item)); if (resolved) { clearDraft(attempt.enrollmentId); setNotice('已确认该 enrollment 为 approved；请在客户端完成配对并核对授权。'); } } };
    }
    const value = await fetchEnrolledClients(signal), resolved = value.clients.some(item => 'client:' + item.id === key && item.status === 'revoked');
    return { resolved, message: '客户端撤销尚未确认；未重发撤销请求。', apply: () => setClients(value.clients) };
  }, attempts.current[key]?.target ? ['client:' + attempts.current[key].target] : []);

  return <main className="clients-page">
    <header className="registry-header"><div><span className="eyebrow">v2 True Direct</span><h1>本地客户端与授权</h1></div><button className="ghost-button" type="button" onClick={() => { if (canLeaveWorkspace()) onBack(); }}>返回 Studio</button></header>
    <button type="button" onClick={() => void polling.refresh()}>刷新客户端</button>
    {error && <div className="alert" role="alert">{error}</div>}
    {Object.entries(refresh.errors).map(([key, message]) => <div key={key} className="alert" role="alert">{message}</div>)}
    {Object.entries(actions.states).map(([key, state]) => <div key={key} role={state.phase === 'pending' ? 'status' : 'alert'}>{state.message} <small>{state.identity}</small>
      {state.phase === 'unknown' && <button type="button" onClick={() => void reconcile(key)}>只读核对结果</button>}
      {state.phase === 'conflict' && <button type="button" onClick={() => void polling.refresh().then(() => actions.clear(key))}>刷新并确认最新状态</button>}
    </div>)}
    {notice && <div className="notice" role="status">{notice}</div>}
    <section className="client-section"><div className="section-title"><div><h2>此浏览器</h2><p>PWA 使用 WebCrypto 包装密钥和本地打包的 libsodium；不会取得长期摄像机密码。</p></div><span>7 天</span></div>
      <ol><li>创建浏览器配对，记下本机显示的八位码。</li><li>管理员在“待批准配对”中输入该码，选择需要的 Camera 和 Profile，然后批准。</li><li>回到此浏览器点击“批准后完成配对”，再载入设备布局。离线保存会排队；恢复连接后同步，冲突由用户选择。</li></ol>
      <div className="browser-pairing"><label><span>设备名称</span><input disabled={actions.blocked('browser-pairing')} value={browserName} maxLength={64} onChange={(event) => setBrowserName(event.target.value)} /></label>
        {!browserPairing && <button className="primary-button" disabled={actions.blocked('browser-pairing') || !window.isSecureContext} onClick={() => void pairBrowser()}>创建浏览器配对</button>}
        {browserPairing?.state === 'pending' && <><strong>配对码：{browserPairing.pairingCode || '已创建'}</strong><span>请在下方待批准项输入该码并选择授权范围。</span><button className="primary-button" disabled={actions.blocked('browser-pairing')} onClick={() => void finishBrowserPairing()}>批准后完成配对</button></>}
        {browserPairing?.state === 'approved' && <strong>已配对 · 离线授权至 {new Date(browserPairing.expiresAt).toLocaleString()}</strong>}
        {!window.isSecureContext && <small>当前不是受信任 HTTPS Secure Context，浏览器配对已禁用。</small>}
      </div>
    </section>
    <section className="client-section"><div className="section-title"><div><h2>待批准配对</h2><p>配对码十分钟有效。只授权实际需要的 Camera、Profile 和操作；可选择创建新设备，或明确更新同平台的已有设备。</p></div><span>{enrollments.filter((item) => item.state === 'pending').length}</span></div>
      {enrollments.filter((item) => item.state === 'pending' || edited[item.id] || actions.states[enrollmentKey(item.id)]).length === 0 ? <div className="registry-empty">暂无待批准客户端</div> : enrollments.filter((item) => item.state === 'pending' || edited[item.id] || actions.states[enrollmentKey(item.id)]).map((enrollment) => <article className="enrollment-card" key={enrollment.id}>
        <header><div><strong>{enrollment.name}</strong><span>{enrollment.platform} · {Math.max(0, Math.ceil((enrollment.expiresAt * 1000 - Date.now()) / 60000))} 分钟后过期</span></div><label><span>配对码</span><input disabled={enrollmentBlocked(enrollment.id)} inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={codes[enrollment.id] ?? ''} onChange={(event) => { setEdited(current => ({ ...current, [enrollment.id]: true })); setCodes(current => ({ ...current, [enrollment.id]: event.target.value.replace(/\D/g, '') })); }} /></label></header>
        <label className="enrollment-target"><span>设备处理方式</span><select disabled={enrollmentBlocked(enrollment.id)} value={updateTargets[enrollment.id] ?? ''} onChange={(event) => { setEdited(current => ({ ...current, [enrollment.id]: true })); setUpdateTargets(current => ({ ...current, [enrollment.id]: event.target.value })); }}><option value="">创建新的已配对设备</option>{clients.filter((client) => client.status === 'active' && client.platform === enrollment.platform).map((client) => <option key={client.id} value={client.id}>更新：{client.name} · {client.cameraCount} 台摄像机</option>)}</select><small>默认创建新设备；如果这是同一浏览器/客户端的重新配对，请选择对应的“更新”。更新会保留设备 ID、替换旧令牌并原子替换 Camera/Profile 授权；旧浏览器会话立即失效。</small></label>
        <fieldset disabled={enrollmentBlocked(enrollment.id)} className="grant-list"><legend>摄像机授权草稿</legend>{cameras.map((camera) => {
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
        })}</fieldset>
        <footer><span>{isBrowserRuntime(enrollment.platform) ? '浏览器 Grant 最长离线 7 天且不包含摄像机凭据。' : '完全离线设备最迟在 30 天 Grant 到期时失效；复用摄像机账号时，立即彻底撤销还需轮换摄像机密码。'}</span><button className="primary-button" disabled={enrollmentBlocked(enrollment.id) || enrollment.state !== 'pending' || enrollment.stale || actions.states[enrollmentKey(enrollment.id)]?.phase === 'conflict'} onClick={() => void approve(enrollment)}>批准并签发</button></footer>
        {(enrollment.stale || enrollment.state !== 'pending') && edited[enrollment.id] && <p role="alert">{enrollment.stale ? '该配对已从服务器列表消失' : `配对状态已变为 ${enrollment.state}`}；保留草稿，禁止向过期或已批准的配对重发授权。</p>}
        {edited[enrollment.id] && <button type="button" disabled={enrollmentBlocked(enrollment.id)} onClick={() => clearDraft(enrollment.id)}>放弃此配对草稿</button>}
      </article>)}
    </section>
    <section className="client-section"><div className="section-title"><h2>已配对设备</h2><span>{clients.length}</span></div>
      {clients.length === 0 ? <div className="registry-empty">尚无已配对设备</div> : <div className="client-list">{clients.map((client) => <article key={client.id}><div><strong>{client.name}</strong><span>{client.platform} · {client.cameraCount} 台摄像机</span></div><dl><div><dt>状态</dt><dd>{client.status}</dd></div><div><dt>最近在线</dt><dd>{new Date(client.lastSeen * 1000).toLocaleString()}</dd></div><div><dt>离线授权到期</dt><dd>{new Date(client.grantExpiresAt * 1000).toLocaleString()}</dd></div></dl>{client.weakRevocation && <p>⚠ 存在复用凭据或专用账号清理失败；彻底撤销可能还需轮换摄像机密码。</p>}<button className="danger-button" disabled={actions.blocked('client:' + client.id) || client.status === 'revoked'} onClick={() => void revoke(client)}>撤销</button></article>)}</div>}
    </section>
  </main>;
}
