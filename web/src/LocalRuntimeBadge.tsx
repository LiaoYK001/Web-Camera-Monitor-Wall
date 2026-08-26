import { useEffect, useState } from 'react';
import { activatePwaUpdate, currentPwaInstallState, installPwa, type PwaInstallState, type PwaUpdateState } from './pwaRuntime';
import { localConfigState, requestPersistentStorage, type LocalConfigState } from './localRuntime';
import { refreshBrowserAuthorization } from './browserEnrollment';

const labels: Record<LocalConfigState, string> = {
  online: '配置：在线',
  'offline-valid': '配置：离线有效',
  'offline-expired': '配置：已过期',
  empty: '配置：未缓存',
};

export default function LocalRuntimeBadge() {
  const [config, setConfig] = useState<LocalConfigState>('empty');
  const [pwa, setPwa] = useState<PwaUpdateState>('installing');
  const [persistent, setPersistent] = useState<boolean | null>(null);
  const [install, setInstall] = useState<PwaInstallState>(currentPwaInstallState());

  useEffect(() => {
    let refreshing = false;
    const refresh = () => {
      if (!navigator.onLine || refreshing) return;
      refreshing = true;
      void refreshBrowserAuthorization()
        .then((expiresAt) => localConfigState(expiresAt !== null).then(setConfig))
        .catch(() => localConfigState().then(setConfig))
        .finally(() => { refreshing = false; });
    };
    void localConfigState().then(setConfig).catch(() => setConfig('empty'));
    refresh();
    const authorizationTimer = window.setInterval(() => {
      void localConfigState().then(setConfig).catch(() => undefined);
      refresh();
    }, 5_000);
    const localChanged = (event: Event) => setConfig((event as CustomEvent<LocalConfigState>).detail);
    const pwaChanged = (event: Event) => setPwa((event as CustomEvent<PwaUpdateState>).detail);
    const installChanged = (event: Event) => setInstall((event as CustomEvent<PwaInstallState>).detail);
    const onlineChanged = () => void localConfigState().then(setConfig);
    window.addEventListener('webobs:local-state', localChanged);
    window.addEventListener('webobs:pwa-state', pwaChanged);
    window.addEventListener('webobs:pwa-install-state', installChanged);
    window.addEventListener('online', onlineChanged);
    window.addEventListener('offline', onlineChanged);
    return () => {
      window.removeEventListener('webobs:local-state', localChanged);
      window.removeEventListener('webobs:pwa-state', pwaChanged);
      window.removeEventListener('webobs:pwa-install-state', installChanged);
      window.removeEventListener('online', onlineChanged);
      window.removeEventListener('offline', onlineChanged);
      window.clearInterval(authorizationTimer);
    };
  }, []);

  return (
    <div className="local-runtime-badge" data-config-state={config}>
      <span>应用：{pwa === 'cached' || pwa === 'update-ready' ? '本地缓存运行' : pwa === 'unsupported' ? '需要受信任 HTTPS' : pwa === 'error' ? '缓存失败' : '正在缓存'}</span>
      <span>{labels[config]}</span>
      <span>安装：{install === 'installed' ? '已安装' : install === 'installable' ? '可安装' : '浏览器模式'}</span>
      {install === 'installable' && <button type="button" onClick={() => void installPwa().then(setInstall)}>安装到本机</button>}
      {persistent === false && <small>浏览器未授予持久存储</small>}
      {persistent === null && config === 'online' && (
        <button type="button" onClick={() => void requestPersistentStorage().then(setPersistent)}>保护离线数据</button>
      )}
      {pwa === 'update-ready' && <button type="button" onClick={activatePwaUpdate}>应用新版本</button>}
    </div>
  );
}
