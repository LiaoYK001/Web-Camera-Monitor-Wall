import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useDesktopWork } from './desktopRuntime';
import { useDraftGuard } from './useDraftGuard';
import { fetchVerifiedArchivedRecording } from './api';

export interface ArchiveSelection { segmentId: string; cameraId: string; }
export interface ArchivePreview extends ArchiveSelection { url: string; }
type ArchiveDownloader = (segmentId: string, cameraId: string, signal: AbortSignal) => Promise<Blob>;

/** Latest selection owns the only download and Blob URL; no async caller-owned notices. */
export function useArchivedRecording(download: ArchiveDownloader = fetchVerifiedArchivedRecording) {
  const active = useRef(false);
  const owner = useRef<{ selection: ArchiveSelection; controller: AbortController } | null>(null);
  const ownedUrl = useRef<string | null>(null);
  const [preview, setPreview] = useState<ArchivePreview | null>(null);
  const [loading, setLoading] = useState<ArchiveSelection | null>(null);
  const [error, setError] = useState('');
  const workId = useId();
  const busy = loading !== null;
  const reportBusy = useCallback(() => setError('归档下载校验中，请取消下载后再切换页面。'), []);
  useDesktopWork(`archive-playback-${workId}`, false, busy);
  useDraftGuard(false, busy, '归档下载尚未结束。', reportBusy);

  const dispose = useCallback(() => {
    const previous = owner.current;
    owner.current = null; // Invalidate before abort listeners can run.
    previous?.controller.abort();
    if (ownedUrl.current) { URL.revokeObjectURL(ownedUrl.current); ownedUrl.current = null; }
  }, []);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; dispose(); };
  }, [dispose]);

  const close = useCallback(() => {
    dispose();
    if (active.current) { setPreview(null); setLoading(null); setError(''); }
  }, [dispose]);

  const select = useCallback(async (segmentId: string, cameraId: string): Promise<void> => {
    if (!active.current) return;
    if (owner.current?.selection.segmentId === segmentId && owner.current.selection.cameraId === cameraId) return;
    dispose();
    const current = { selection: { segmentId, cameraId }, controller: new AbortController() };
    owner.current = current;
    setPreview(null); setLoading(current.selection); setError('');
    const owns = () => active.current && owner.current === current && !current.controller.signal.aborted;
    try {
      const blob = await download(segmentId, cameraId, current.controller.signal);
      if (!owns()) return;
      const url = URL.createObjectURL(blob);
      if (!owns()) { URL.revokeObjectURL(url); return; }
      ownedUrl.current = url;
      setPreview({ ...current.selection, url });
      setError('');
    } catch (reason) {
      if (owns()) setError(reason instanceof DOMException && reason.name === 'TimeoutError'
        ? '归档下载校验超时，请检查网络后重试。'
        : reason instanceof Error ? reason.message : '归档回放校验失败');
    } finally {
      if (owns()) { owner.current = null; setLoading(null); }
    }
  }, [dispose, download]);

  return { preview, loading, busy, error, select, close };
}
