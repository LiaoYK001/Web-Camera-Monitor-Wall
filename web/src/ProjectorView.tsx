import { useCallback, useEffect, useRef, useState } from 'react';
import { connectSceneEvents, fetchScene, fetchStudio } from './api';
import DirectPreview from './DirectPreview';
import { loadActiveLocalConfigProfile } from './localRuntime';
import ProgramPreview from './ProgramPreview';
import { projectorSceneFromHash, type ProjectorMode } from './projector';
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
  const [sceneId] = useState(() => projectorSceneFromHash(window.location.hash));
  const [sceneError, setSceneError] = useState('');
  const [hintVisible, setHintVisible] = useState(true);
  const hintTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    if (sceneId) {
      let reading = false;
      const refresh = async () => {
        if (reading || controller.signal.aborted) return;
        reading = true;
        try {
          const [remote, profile] = await Promise.all([fetchStudio(controller.signal).catch(() => null), loadActiveLocalConfigProfile().catch(() => null)]);
          if (controller.signal.aborted) return;
          const studio = profile?.studio ?? remote;
          if (!studio) { setSceneError('场景暂时无法读取，正在重试。'); return; }
          const selected = studio.scenes.find((value) => value.id === sceneId);
          setScene(selected ?? null); setSceneError(selected ? '' : '此场景已删除或不在当前配置中。');
          if (selected) document.title = `${selected.name} · 场景投影`;
        } finally { reading = false; }
      };
      void refresh();
      const timer = window.setInterval(() => void refresh(), 5000);
      const disconnect = connectSceneEvents(() => void refresh(), () => undefined);
      const focus = () => void refresh(); window.addEventListener('focus', focus);
      return () => { controller.abort(); window.clearInterval(timer); disconnect(); window.removeEventListener('focus', focus); };
    }
    let usesProfile = false;
    void fetchScene(controller.signal).then((value) => { if (!controller.signal.aborted && !usesProfile) setScene(value); }).catch(() => undefined);
    void loadActiveLocalConfigProfile().then((profile) => {
      if (controller.signal.aborted) return;
      const selected = profile?.studio.scenes.find((candidate) => candidate.id === profile.studio.programSceneId);
      if (selected) { usesProfile = true; setScene(selected); }
    }).catch(() => undefined);
    // The wall publishes committed scenes over the same WebSocket; the
    // projector follows them so a second display never shows a stale picture.
    const disconnect = connectSceneEvents((event) => { if (!usesProfile) setScene(event.scene); }, () => undefined);
    return () => { controller.abort(); disconnect(); };
  }, [sceneId]);

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
      data-projector-scene={sceneId ?? 'program'}
      onDoubleClick={toggleFullscreen}
      title="双击全屏 · Esc 关闭"
    >
      {mode === 'composite' && !sceneId
        ? <ProgramPreview silent aspectRatio={scene ? `${scene.canvas.width} / ${scene.canvas.height}` : DEFAULT_ASPECT} />
        : scene
          ? <DirectPreview compact sceneLayout={Boolean(sceneId)} scene={scene} />
          : <p className="projector-waiting" role="status">{sceneError || '正在连接场景画面…'}</p>}
      {scene && sceneError && <span className="projector-hint" role="status">{sceneError}</span>}
      {hintVisible && <div className="projector-hint" role="status">
        <span>{sceneId ? `${scene?.name ?? '场景投影'} · 固定场景` : '投影窗口 · 只显示最终画面'}</span>
        <span>双击全屏 · Esc 关闭</span>
      </div>}
    </div>
  );
}
