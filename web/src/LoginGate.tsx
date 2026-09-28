import { type FormEvent, type ReactNode, useEffect, useState } from 'react';
import { fetchAuthSession, fetchFirstRunStatus, login, logout, registerFirstAdmin, type AuthSession } from './api';
import { clearPrivateRuntimeState } from './localRuntime';

type GateSession = AuthSession & { offlineAuthorized?: boolean; unavailable?: boolean };
const ACTIVE_ACCOUNT_KEY = 'webobs-active-account';

async function activateAccount(session: AuthSession): Promise<void> {
  if (!session.authenticated || !session.user) return;
  const previous = window.localStorage.getItem(ACTIVE_ACCOUNT_KEY);
  if (previous && previous !== session.user) await clearPrivateRuntimeState();
  window.localStorage.setItem(ACTIVE_ACCOUNT_KEY, session.user);
}

export default function LoginGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<GateSession | null>(null);
  const [checkAttempt, setCheckAttempt] = useState(0);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [registrationOpen, setRegistrationOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fetchAuthSession(controller.signal), fetchFirstRunStatus()])
      .then(async ([current, setup]) => {
        if (controller.signal.aborted) return;
        await activateAccount(current);
        if (!controller.signal.aborted) { setSession(current); setRegistrationOpen(setup.registrationOpen); }
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setSession({ authenticated: false, authenticationEnabled: true, unavailable: true });
      });
    return () => controller.abort();
  }, [checkAttempt]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      if (registrationOpen) await registerFirstAdmin(username, password);
      const current = await login(username, password);
      await activateAccount(current);
      setSession(current);
      setRegistrationOpen(false);
      setPassword('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (!session) return <main className="login-screen"><div className="login-card"><p>正在检查安全会话…</p></div></main>;
  if (session.unavailable) return <main className="login-screen"><div className="login-card">
    <span className="eyebrow">Web Camera Monitor Wall</span>
    <h1>本地服务暂不可用</h1>
    <p>未检测到可用的控制服务。请确认开发后端正在运行后重试。</p>
    <button className="primary-button" type="button" onClick={() => { setSession(null); setCheckAttempt((value) => value + 1); }}>重新检查</button>
  </div></main>;
  if (session.authenticationEnabled === false || session.authenticated) return (
    <>
      {children}
      {session.authenticated && !session.offlineAuthorized && (
        <button className="session-logout" type="button" onClick={() => void logout()
          .finally(() => clearPrivateRuntimeState())
          .finally(() => setSession({ authenticated: false, authenticationEnabled: true }))}>
          退出登录
        </button>
      )}
      {session.offlineAuthorized && <span className="offline-session">离线授权模式 · 修改只保存在本机</span>}
    </>
  );
  return (
    <main className="login-screen">
      <form className="login-card" onSubmit={(event) => void submit(event)}>
        <span className="eyebrow">Web Camera Monitor Wall</span>
        <h1>{registrationOpen ? '创建管理员账号' : '登录监控工作台'}</h1>
        <p>{registrationOpen ? '首次部署请设置管理员用户名和密码。之后可在“管理”中添加其他账号。' : '会话在每次正常访问后续期；连续 7 天未访问才会失效。'}</p>
        <label><span>用户名</span><input autoComplete="username" minLength={registrationOpen ? 3 : undefined} maxLength={64} value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        <label><span>密码</span><input type="password" autoComplete={registrationOpen ? 'new-password' : 'current-password'} minLength={registrationOpen ? 16 : undefined} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <div className="alert" role="alert">{error}</div>}
        <button className="primary-button" disabled={submitting || !username || (registrationOpen ? password.length < 16 : !password)} type="submit">{submitting ? '处理中…' : registrationOpen ? '创建并登录' : '登录'}</button>
        <small>登录 Cookie 使用 HttpOnly 和 SameSite=Strict；{window.location.protocol === 'https:' ? 'HTTPS 下启用 Secure 属性。' : '本机 HTTP 开发模式下由会话服务器保护。'}</small>
      </form>
    </main>
  );
}
