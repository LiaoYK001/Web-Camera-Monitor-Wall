import { type FormEvent, type ReactNode, useEffect, useState } from 'react';
import { fetchAuthSession, login, logout, type AuthSession } from './api';

export default function LoginGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchAuthSession(controller.signal)
      .then(setSession)
      .catch(() => setSession({ authenticated: false, authenticationEnabled: true }));
    return () => controller.abort();
  }, []);

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
  if (session.authenticationEnabled === false || session.authenticated) return (
    <>
      {children}
      {session.authenticated && (
        <button className="session-logout" type="button" onClick={() => void logout().then(() => setSession({ authenticated: false, authenticationEnabled: true }))}>
          退出登录
        </button>
      )}
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
