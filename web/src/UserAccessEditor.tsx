import { useEffect, useState } from 'react';
import { fetchClusterUsers, patchClusterUser } from './api';
import type { ClusterRole, ClusterUser } from './types';
import type { ManagementActions } from './useManagementActions';

const scopesText = (user: ClusterUser) => user.scopes.map(scope => scope.kind + ':' + scope.id).join(', ');
const access = (user: ClusterUser) => JSON.stringify({ roles: [...user.roles].sort(), scopes: user.scopes.map(scope => scope.kind + ':' + scope.id).sort(), enabled: user.enabled });

export default function UserAccessEditor({ user, roles, actions, onSaved, onRefresh, onDirty }: {
  user: ClusterUser; roles: Array<{ id: ClusterRole; permissions: string[] }>; actions: ManagementActions;
  onSaved: (user: ClusterUser) => void; onRefresh: () => Promise<void>; onDirty: (id: string, dirty: boolean) => void;
}) {
  const [baseline, setBaseline] = useState(user);
  const [selectedRoles, setSelectedRoles] = useState<ClusterRole[]>(user.roles);
  const [scopeText, setScopeText] = useState(scopesText(user));
  const [enabled, setEnabled] = useState(user.enabled);
  const [validation, setValidation] = useState('');
  const key = 'user:' + user.id, state = actions.states[key];
  const dirty = JSON.stringify(selectedRoles) !== JSON.stringify(baseline.roles) || scopeText !== scopesText(baseline) || enabled !== baseline.enabled;
  const conflict = user.revision !== baseline.revision || state?.phase === 'conflict';
  const blocked = actions.blocked(key);
  const reset = (next: ClusterUser) => {
    setBaseline(next); setSelectedRoles(next.roles); setScopeText(scopesText(next)); setEnabled(next.enabled); setValidation('');
  };
  useEffect(() => {
    if (!dirty && !blocked && !conflict) reset(user);
    // A dirty draft deliberately retains its original revision, never an implicit rebase.
    else if (!dirty && !blocked && state?.phase !== 'conflict') reset(user);
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { onDirty(user.id, dirty); return () => onDirty(user.id, false); }, [dirty, user.id, onDirty]);
  const desired = (): ClusterUser => ({ ...baseline, roles: selectedRoles, enabled,
    scopes: scopeText.split(',').map(value => value.trim()).filter(Boolean).map(value => {
      const separator = value.indexOf(':'), kind = value.slice(0, separator), id = value.slice(separator + 1);
      if (separator < 1 || !['camera', 'group'].includes(kind) || !/^[A-Za-z0-9._-]{1,64}$/.test(id))
        throw new Error('范围必须使用 camera:id 或 group:id，多个范围用逗号分隔。');
      return { kind: kind as 'camera' | 'group', id };
    }) });
  const save = async () => {
    if (blocked || conflict || !dirty) return;
    let draft: ClusterUser;
    try { draft = desired(); if (!draft.roles.length) throw new Error('用户至少需要一个角色。'); }
    catch (reason) { setValidation((reason as Error).message); return; }
    setValidation('');
    await actions.run(key, '保存权限', user.id + ' · revision ' + baseline.revision,
      signal => patchClusterUser(user.id, baseline.revision, { roles: draft.roles, scopes: draft.scopes, enabled: draft.enabled }, signal),
      saved => { const next = { ...draft, revision: saved.revision }; reset(next); onSaved(next); });
    void onRefresh();
  };
  const reconcile = () => actions.reconcile(key, async signal => {
    const latest = (await fetchClusterUsers(signal)).users.find(item => item.id === user.id);
    const resolved = Boolean(latest && latest.revision > baseline.revision && access(latest) === access(desired()));
    return { resolved, message: '服务器状态尚不能确认此次保存；草稿与原 revision 已保留，请联系管理员核对，勿重复提交。',
      apply: () => { if (latest) { onSaved(latest); if (resolved) reset(latest); } } };
  });
  return <article className="user-access-card" aria-label={'用户权限 ' + user.username}>
    <div><strong>{user.username}</strong><small>{user.enabled ? '已启用' : '已停用'} · revision {user.revision}</small></div>
    <fieldset disabled={blocked}><legend>角色</legend>{roles.map(role => <label key={role.id} title={role.permissions.join(', ')}>
      <input type="checkbox" checked={selectedRoles.includes(role.id)} onChange={() => setSelectedRoles(current => current.includes(role.id) ? current.filter(item => item !== role.id) : [...current, role.id])} />{role.id}</label>)}</fieldset>
    <label>Camera/Group 范围<input disabled={blocked} value={scopeText} placeholder="camera:front-door, group:office" onChange={event => setScopeText(event.target.value)} /></label>
    <div className="user-access-actions"><label><input type="checkbox" disabled={blocked} checked={enabled} onChange={event => setEnabled(event.target.checked)} />启用</label>
      <button type="button" disabled={blocked || conflict || !dirty || !selectedRoles.length} onClick={() => void save()}>{state?.phase === 'pending' ? '保存中…' : '保存权限'}</button></div>
    {validation && <p role="alert">{validation}</p>}
    {conflict && <div role="alert">revision 冲突：服务器为 {user.revision}，草稿基于 {baseline.revision}。草稿未被覆盖。
      <button type="button" disabled={blocked || user.revision === baseline.revision} onClick={() => { setBaseline(user); actions.clear(key); }}>保留草稿并采用新 revision</button>
      <button type="button" disabled={blocked} onClick={() => { reset(user); actions.clear(key); }}>放弃草稿并载入服务器值</button></div>}
    {state && <p role={state.phase === 'pending' ? 'status' : 'alert'}>{state.message}</p>}
    {state?.phase === 'unknown' && <button type="button" onClick={() => void reconcile()}>只读核对权限</button>}
  </article>;
}
