import { type FormEvent, type ReactNode, useEffect, useState } from 'react';
import { fetchAuthSession, login, logout, type AuthSession } from './api';
import { clearPrivateRuntimeState, hasLocalConfigProfiles, localConfigState } from './localRuntime';

type GateSession = AuthSession & { offlineAuthorized?: boolean; unavailable?: boolean };

export default function LoginGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<GateSession | null>(null);
  const [checkAttempt, setCheckAttempt] = useState(0);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchAuthSession(controller.signal)
      .then(setSession)
      .catch(() => {
        if (controller.signal.aborted) return;
        void Promise.all([
          localConfigState().catch(() => 'empty' as const),
          hasLocalConfigProfiles().catch(() => false),
        ]).then(([state, hasProfiles]) => {
          if (controller.signal.aborted) return;
          setSession({
            // A failed session probe is a connectivity state, not evidence that
            // credentials are required. Showing a password form here used to
            // trap local development whenever the backend briefly restarted.
            authenticated: state === 'offline-valid',
            authenticationEnabled: false,
            offlineAuthorized: state === 'offline-valid',
            unavailable: state !== 'offline-valid' && !hasProfiles,
          });
        });
      });
    return () => controller.abort();
  }, [checkAttempt]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      setSession(await login(username, password));
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
    <p>未检测到可用的控制服务。请确认 Docker/Vite 后端正在运行后重试；当前不会要求输入用户名或密码。</p>
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
        <h1>登录监控工作台</h1>
        <p>会话在每次正常访问后续期；连续 7 天未访问才会失效。</p>
        <label><span>用户名</span><input autoComplete="username" maxLength={64} value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        <label><span>密码</span><input type="password" autoComplete="current-password" maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <div className="alert" role="alert">{error}</div>}
        <button className="primary-button" disabled={submitting || !username || !password} type="submit">{submitting ? '登录中…' : '登录'}</button>
        <small>Cookie 使用 HttpOnly、Secure、SameSite=Strict；页面脚本无法读取 token。</small>
      </form>
    </main>
  );
}
