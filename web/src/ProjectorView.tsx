import { useCallback, useEffect, useRef, useState } from 'react';
import { connectSceneEvents, fetchScene } from './api';
import DirectPreview from './DirectPreview';
import ProgramPreview from './ProgramPreview';
import type { ProjectorMode } from './projector';
import type { SceneDocument } from './types';

const DEFAULT_ASPECT = '16 / 9';
const HINT_VISIBLE_MS = 3200;

/**
 * F6-07: the detachable window shows the final picture only - no workspace
 * shell, docks, header, footer or page navigation.  It reuses the exact preview
 * components the monitor wall uses, so the projector cannot drift from what the
 * wall shows.  Esc closes it and a double click toggles fullscreen, matching the
 * OBS scene projector behaviour.
 */
export default function ProjectorView({ mode }: { mode: ProjectorMode }) {
  const [scene, setScene] = useState<SceneDocument | null>(null);
  const [hintVisible, setHintVisible] = useState(true);
  const hintTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    fetchScene(controller.signal).then(setScene).catch(() => undefined);
    // The wall publishes committed scenes over the same WebSocket; the
    // projector follows them so a second display never shows a stale picture.
    const disconnect = connectSceneEvents((event) => setScene(event.scene), () => undefined);
    return () => { controller.abort(); disconnect(); };
  }, []);

  useEffect(() => {
    const revealHint = () => {
      window.clearTimeout(hintTimer.current);
      setHintVisible(true);
      hintTimer.current = window.setTimeout(() => setHintVisible(false), HINT_VISIBLE_MS);
    };
    revealHint();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') window.close(); };
    window.addEventListener('mousemove', revealHint);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.clearTimeout(hintTimer.current);
      window.removeEventListener('mousemove', revealHint);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen().catch(() => undefined);
  }, []);

  return (
    <div
      className="projector-shell"
      data-projector-mode={mode}
      onDoubleClick={toggleFullscreen}
      title="双击全屏 · Esc 关闭"
    >
      {mode === 'composite'
        ? <ProgramPreview aspectRatio={scene ? `${scene.canvas.width} / ${scene.canvas.height}` : DEFAULT_ASPECT} />
        : scene
          ? <DirectPreview compact scene={scene} />
          : <p className="projector-waiting" role="status">正在连接节目画面…</p>}
      {hintVisible && <div className="projector-hint" role="status">
        <span>投影窗口 · 只显示最终画面</span>
        <span>双击全屏 · Esc 关闭</span>
      </div>}
    </div>
  );
}
