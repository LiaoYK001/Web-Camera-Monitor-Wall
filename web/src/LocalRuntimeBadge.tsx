import { useEffect, useState } from 'react';
import { activatePwaUpdate, currentPwaInstallState, installPwa, type PwaInstallState, type PwaUpdateState } from './pwaRuntime';

export default function LocalRuntimeBadge() {
  const [pwa, setPwa] = useState<PwaUpdateState>('installing');
  const [install, setInstall] = useState<PwaInstallState>(currentPwaInstallState());
  const [accountSync, setAccountSync] = useState<'checking' | 'saved' | 'offline'>('checking');
  useEffect(() => {
    const pwaChanged = (event: Event) => setPwa((event as CustomEvent<PwaUpdateState>).detail);
    const installChanged = (event: Event) => setInstall((event as CustomEvent<PwaInstallState>).detail);
    const accountChanged = (event: Event) => setAccountSync((event as CustomEvent<'saved' | 'offline'>).detail);
    window.addEventListener('webobs:pwa-state', pwaChanged);
    window.addEventListener('webobs:pwa-install-state', installChanged);
    window.addEventListener('webobs:account-sync', accountChanged);
    return () => {
      window.removeEventListener('webobs:pwa-state', pwaChanged);
      window.removeEventListener('webobs:pwa-install-state', installChanged);
      window.removeEventListener('webobs:account-sync', accountChanged);
    };
  }, []);
  return <div className="local-runtime-badge">
    <span>账号配置：{accountSync === 'saved' ? '已同步' : accountSync === 'offline' ? '待连接服务器' : '检查中'}</span>
    <span>应用：{pwa === 'cached' || pwa === 'update-ready' ? '本地缓存运行' : pwa === 'unsupported' ? '需要受信任 HTTPS' : pwa === 'error' ? '缓存失败' : '正在缓存'}</span>
    <span>安装：{install === 'installed' ? '已安装' : install === 'installable' ? '可安装' : '浏览器模式'}</span>
    {install === 'installable' && <button type="button" onClick={() => void installPwa().then(setInstall)}>安装到本机</button>}
    {pwa === 'update-ready' && <button type="button" onClick={activatePwaUpdate}>应用新版本</button>}
  </div>;
}
