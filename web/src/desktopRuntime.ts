import { useEffect } from 'react';

export interface DesktopSettings { autoCheck: boolean; autoDownload: boolean; startAtLogin: boolean; lanEnabled: boolean; lanPort: number; recordingDirectory: string; minimizeToTray: boolean }
export interface DesktopStatus {
  app?: { version: string; platform: string; architecture: string; packaged: boolean };
  runtime: { phase: string; detail?: string; recordings?: string; lan?: { enabled: boolean; addresses?: string[]; certificate?: string; trustSteps?: string; firewallCommands?: string[] } };
  update: { phase: string; message?: string; version?: string; kind?: 'major' | 'minor' | 'patch' | null; releaseNotes?: string; percent?: number; signed?: boolean; lastCheckedAt?: string };
  settings: DesktopSettings;
  recovery: { from: string; to: string; hasInstaller: boolean; snapshot: string } | null;
}
export interface DesktopDisplay { id: number; label: string; primary: boolean; bounds: { x: number; y: number; width: number; height: number } }
export interface DesktopBridge {
  version: number;
  status(): Promise<DesktopStatus>;
  settings(): Promise<DesktopSettings>;
  saveSettings(changes: Partial<DesktopSettings>): Promise<DesktopSettings>;
  chooseRecordingDirectory(): Promise<DesktopSettings>;
  displays(): Promise<DesktopDisplay[]>;
  projector(options: { sceneId?: string; mode: 'direct' | 'composite'; displayId?: number; fullscreen?: boolean }): Promise<{ id: number }>;
  checkUpdate(): Promise<unknown>; downloadUpdate(): Promise<unknown>; installUpdate(): Promise<unknown>;
  restartServices(): Promise<DesktopStatus>; backup(): Promise<DesktopStatus>; restore(): Promise<DesktopStatus>;
  restorePrevious(): Promise<DesktopStatus>; openPreviousInstaller(): Promise<DesktopStatus>;
  reportWork(value: { dirty: boolean; exporting: boolean }): Promise<unknown>;
  onStatus(callback: (status: DesktopStatus) => void): () => void;
}
declare global { interface Window { webobsDesktop?: DesktopBridge; webobsUpdateWork?: () => { dirty: boolean; exporting: boolean } } }
const work = new Map<string, { dirty: boolean; exporting: boolean }>();
const updateWork = () => ({ dirty: [...work.values()].some(value => value.dirty), exporting: [...work.values()].some(value => value.exporting) });
// Read-only flags for native Android's fixed install preflight. No payload or native command bridge.
Object.defineProperty(window, 'webobsUpdateWork', { value: updateWork, configurable: true });
const announce = () => { void window.webobsDesktop?.reportWork(updateWork()).catch(() => undefined); };
export function useDesktopWork(key: string, dirty: boolean, exporting = false) {
  useEffect(() => {
    work.set(key, { dirty, exporting }); announce();
    return () => { work.delete(key); announce(); };
  }, [key, dirty, exporting]);
}
export function desktopTask(key: string): () => void {
  work.set(key, { dirty: false, exporting: true }); announce();
  return () => { work.delete(key); announce(); };
}
export async function fetchRuntimeInfo(signal?: AbortSignal): Promise<{ platform: string; go2rtcRtspBase: string; onlineSourcesEnabled?: boolean }> {
  const response = await fetch('/api/v1/runtime/info', { credentials: 'same-origin', cache: 'no-store', signal });
  if (!response.ok) throw new Error('运行时地址不可用，请刷新或检查后端版本。');
  const info = await response.json() as { platform: string; go2rtcRtspBase: string; onlineSourcesEnabled?: boolean };
  if (!/^rtsp:\/\/127\.0\.0\.1:\d{1,5}\/$/.test(info.go2rtcRtspBase)) throw new Error('后端 RTSP 地址无效');
  return info;
}
