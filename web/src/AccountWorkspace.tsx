import { useEffect, useRef, useState, type FormEvent } from 'react';
import { changeAccountPassword, fetchAccountProfile, updateAccountProfile, type AccountProfile } from './api';
import { useDesktopWork } from './desktopRuntime';
import { useDraftGuard } from './useDraftGuard';
import { canLeaveWorkspace } from './navigationGuard';

import { avatarChoices, roleLabel } from './accountPresentation';

const permissionLabels: Record<string, string> = {
  'live.view': '查看实时画面', 'scene.read': '读取场景', 'scene.write': '编辑场景',
  'device.manage': '管理设备', 'ptz.control': '云台控制', 'talk.control': '对讲',
  'snapshot.create': '抓图', 'playback.view': '查看回放', 'export.create': '导出录像',
  'recording.lock': '锁定录像', 'recording.delete': '删除录像', 'event.ack': '确认事件',
  'analytics.view': '查看分析', 'analytics.run': '运行分析', 'analytics.manage': '管理分析',
  'storage.manage': '管理存储', 'node.manage': '管理节点', 'settings.manage': '管理设置',
  'user.manage': '管理用户', 'audit.view': '查看审计', 'metrics.view': '查看指标',
};

export default function AccountWorkspace({ onAdmin }: { onAdmin: () => void }) {
  const [profile, setProfile] = useState<AccountProfile | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [avatar, setAvatar] = useState<AccountProfile['avatar']>('person');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState<'profile' | 'password' | null>(null);
  const running = useRef(false);
  useEffect(() => { const controller = new AbortController();
    setLoading(true); setError('');
    void fetchAccountProfile(controller.signal).then((value) => {
      if (!controller.signal.aborted) { setProfile(value); setDisplayName(value.displayName); setAvatar(value.avatar); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '账号信息读取失败');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort(); }, [reload]);
  const profileDirty = Boolean(profile && (displayName.trim() !== profile.displayName || avatar !== profile.avatar));
  const dirty = profileDirty || Boolean(currentPassword || newPassword || confirmPassword);
  const passwordValid = Boolean(currentPassword && new TextEncoder().encode(newPassword).length >= 16 && newPassword === confirmPassword);
  useDesktopWork('account-edit', dirty, Boolean(busy));
  useDraftGuard(dirty, Boolean(busy), '账号修改尚未保存，离开会丢弃这些输入，继续？', setNotice);
  const saveProfile = async (event: FormEvent) => {
    event.preventDefault();
    if (running.current || !profileDirty || !displayName.trim()) return;
    running.current = true; setBusy('profile'); setError(''); setNotice('');
    try { const updated = await updateAccountProfile({ displayName: displayName.trim(), avatar });
      setProfile(updated); setDisplayName(updated.displayName); setAvatar(updated.avatar);
      setNotice('个人信息已保存'); window.dispatchEvent(new Event('webobs:account-profile-updated'));
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败，输入已保留，可重试'); }
    finally { running.current = false; setBusy(null); }
  };
  const savePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (running.current || !passwordValid) return;
    running.current = true; setBusy('password'); setError(''); setNotice('');
    try { await changeAccountPassword(currentPassword, newPassword); setCurrentPassword(''); setNewPassword(''); setConfirmPassword(''); setNotice('密码已更新'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '修改密码失败，输入已保留，可重试'); }
    finally { running.current = false; setBusy(null); }
  };
  return <section className="account-workspace page-panel">
    <header className="page-heading"><div><span className="eyebrow">Account</span><h1>我的账号</h1>
      <p>{profile ? `${profile.username} · ${profile.roles.map(roleLabel).join('、')}` : loading ? '正在读取账号信息…' : '账号信息暂不可用'}</p></div>
      {profile?.permissions.includes('user.manage') && <button type="button" onClick={() => { if (canLeaveWorkspace()) onAdmin(); }}>管理用户与审计</button>}</header>
    {error && <p className="inline-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!profile && !loading && <button type="button" onClick={() => setReload((value) => value + 1)}>重新读取账号信息</button>}
    {profile && <div className="account-grid"><form aria-label="个人信息" aria-busy={busy === 'profile'} onSubmit={(event) => void saveProfile(event)}><h2>个人信息</h2><fieldset className="account-form-fields" disabled={Boolean(busy)}>
      <legend className="sr-only">个人信息</legend><label>昵称<input required maxLength={64} value={displayName} onChange={(event) => { setDisplayName(event.target.value); setNotice(''); }} /></label>
      <fieldset><legend>头像</legend><div className="avatar-options">{avatarChoices.map((choice) =>
        <label key={choice.id}><input type="radio" name="avatar" value={choice.id} checked={avatar === choice.id}
          onChange={() => { setAvatar(choice.id); setNotice(''); }} /><span aria-hidden="true">{choice.icon}</span>{choice.label}</label>)}</div></fieldset>
      <span className={`save-mode-badge ${profileDirty ? 'unsaved' : ''}`}>{profileDirty ? '有未保存修改' : '与账号同步'}</span>
      <button type="submit" disabled={!profileDirty || !displayName.trim()}>{busy === 'profile' ? '正在保存…' : '保存个人信息'}</button>
    </fieldset></form><form aria-label="修改密码" aria-busy={busy === 'password'} onSubmit={(event) => void savePassword(event)}><h2>修改密码</h2><fieldset className="account-form-fields" disabled={Boolean(busy)}><legend className="sr-only">修改密码</legend>
      <label>当前密码<input required type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => { setCurrentPassword(event.target.value); setNotice(''); }} /></label>
      <label>新密码（至少 16 字节）<input required type="password" autoComplete="new-password" aria-describedby="account-password-help" value={newPassword} onChange={(event) => { setNewPassword(event.target.value); setNotice(''); }} /></label>
      <small id="account-password-help">至少 16 字节；中文等字符会占用多个字节。</small>
      <label>确认新密码<input required type="password" autoComplete="new-password" aria-invalid={Boolean(confirmPassword && confirmPassword !== newPassword)} aria-describedby="account-password-match" value={confirmPassword} onChange={(event) => { setConfirmPassword(event.target.value); setNotice(''); }} /></label>
      <small id="account-password-match" role="status">{confirmPassword && confirmPassword !== newPassword ? '两次输入的新密码不一致' : '请再次输入新密码，确认无误后保存。'}</small>
      <button type="submit" disabled={!passwordValid}>{busy === 'password' ? '正在更新…' : '更新密码'}</button>
    </fieldset></form></div>}
    {profile && <section className="account-acl"><h2>权限审查清单</h2><p>只读展示当前账号的有效权限，方便核对角色与授权范围。</p>
      <p>角色：{profile.roles.map(roleLabel).join('、')} · 范围：{profile.scopes.length ? profile.scopes.map((scope) => `${scope.kind} ${scope.id}`).join('、') : '无单独范围限制'}</p>
      <div className="acl-grid">{profile.acl.map((item) => <div key={item.permission}><span aria-label={item.allowed ? '允许' : '未授权'}>{item.allowed ? '✓' : '—'}</span><span>{permissionLabels[item.permission] ?? item.permission}</span><code>{item.permission}</code></div>)}</div>
    </section>}
  </section>;
}
