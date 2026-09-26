import { useEffect, useState, type FormEvent } from 'react';
import { changeAccountPassword, fetchAccountProfile, updateAccountProfile, type AccountProfile } from './api';

export const avatarChoices: Array<{ id: AccountProfile['avatar']; icon: string; label: string }> = [
  { id: 'person', icon: '●', label: '人物' }, { id: 'camera', icon: '▣', label: '相机' },
  { id: 'shield', icon: '◆', label: '盾牌' }, { id: 'eye', icon: '◉', label: '眼睛' },
  { id: 'star', icon: '★', label: '星星' }, { id: 'sun', icon: '☀', label: '太阳' },
];

const roleLabels: Record<string, string> = { admin: '管理员', operator: '操作员', viewer: '观众',
  auditor: '审计员', exporter: '导出员' };
export const roleLabel = (role: string) => roleLabels[role] ?? role;

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
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { const controller = new AbortController();
    void fetchAccountProfile(controller.signal).then((value) => { setProfile(value); setDisplayName(value.displayName); setAvatar(value.avatar); })
      .catch((error: unknown) => setMessage(error instanceof Error ? error.message : '账号信息读取失败'));
    return () => controller.abort(); }, []);
  const saveProfile = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage('');
    try { const updated = await updateAccountProfile({ displayName: displayName.trim(), avatar });
      setProfile(updated); setMessage('个人信息已保存'); window.dispatchEvent(new Event('webobs:account-profile-updated'));
    } catch (error) { setMessage(error instanceof Error ? error.message : '保存失败'); }
    finally { setBusy(false); }
  };
  const savePassword = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage('');
    try { await changeAccountPassword(currentPassword, newPassword); setCurrentPassword(''); setNewPassword(''); setMessage('密码已更新'); }
    catch (error) { setMessage(error instanceof Error ? error.message : '修改密码失败'); }
    finally { setBusy(false); }
  };
  return <section className="account-workspace page-panel">
    <header className="page-heading"><div><span className="eyebrow">Account</span><h1>我的账号</h1>
      <p>{profile ? `${profile.username} · ${profile.roles.map(roleLabel).join('、')}` : '正在读取账号信息…'}</p></div>
      {profile?.permissions.includes('user.manage') && <button type="button" onClick={onAdmin}>管理用户与审计</button>}</header>
    {message && <p role="status">{message}</p>}
    {profile && <div className="account-grid"><form onSubmit={(event) => void saveProfile(event)}>
      <h2>个人信息</h2><label>昵称<input maxLength={64} value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
      <fieldset><legend>头像</legend><div className="avatar-options">{avatarChoices.map((choice) =>
        <label key={choice.id}><input type="radio" name="avatar" value={choice.id} checked={avatar === choice.id}
          onChange={() => setAvatar(choice.id)} /><span aria-hidden="true">{choice.icon}</span>{choice.label}</label>)}</div></fieldset>
      <button type="submit" disabled={busy || !displayName.trim()}>保存个人信息</button>
    </form><form onSubmit={(event) => void savePassword(event)}><h2>修改密码</h2>
      <label>当前密码<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
      <label>新密码（至少 16 字节）<input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label>
      <button type="submit" disabled={busy || !currentPassword || new TextEncoder().encode(newPassword).length < 16}>更新密码</button>
    </form></div>}
    {profile && <section className="account-acl"><h2>权限审查清单</h2><p>只读展示当前账号的有效权限，方便核对角色与授权范围。</p>
      <p>角色：{profile.roles.map(roleLabel).join('、')} · 范围：{profile.scopes.length ? profile.scopes.map((scope) => `${scope.kind} ${scope.id}`).join('、') : '无单独范围限制'}</p>
      <div className="acl-grid">{profile.acl.map((item) => <div key={item.permission}><span aria-label={item.allowed ? '允许' : '未授权'}>{item.allowed ? '✓' : '—'}</span><span>{permissionLabels[item.permission] ?? item.permission}</span><code>{item.permission}</code></div>)}</div>
    </section>}
  </section>;
}
