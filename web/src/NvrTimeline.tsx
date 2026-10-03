import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNvrExportJobs } from './useNvrExportJobs';
import { NvrExportPanel } from './NvrExportPanel';
import {
  createNvrSnapshot,
  createPlaybackLease,
  deleteNvrSegment,
  fetchNvrStatus,
  fetchNvrTimeline,
  setNvrLock,
  releasePlaybackLease,
} from './api';
import type { NvrSegment, NvrTimeline as TimelineDocument, NvrTimelineCamera } from './types';

const DAY_MS = 86_400_000;
const clamp = (value: number, minimum: number, maximum: number) => Math.min(Math.max(value, minimum), maximum);
const utcDay = (value: string) => Date.parse(`${value}T00:00:00.000Z`);
const todayUtc = () => new Date().toISOString().slice(0, 10);

function formatTime(value: number, timeZone: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZoneName: 'short',
  }).format(value);
}

function playable(camera: NvrTimelineCamera, cursor: number): NvrSegment | undefined {
  return camera.segments.find((segment) => segment.startUtcMs <= cursor && cursor < segment.endUtcMs
    && !['missing', 'corrupt', 'deleted'].includes(segment.integrity));
}

export default function NvrTimeline({ onBack }: { onBack: () => void }) {
  const [day, setDay] = useState(todayUtc());
  const [timeZone, setTimeZone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  const [cameraIds, setCameraIds] = useState<string[]>([]);
  const [availableIds, setAvailableIds] = useState<string[]>([]);
  const [timeline, setTimeline] = useState<TimelineDocument | null>(null);
  const [cursor, setCursor] = useState(utcDay(todayUtc()));
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [starting, setStarting] = useState(false);
  const playIntent = useRef(0);
  const playLock = useRef(false);
  const videoIntents = useRef(new WeakMap<HTMLVideoElement, number>());
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const exports = useNvrExportJobs();
  const [duration, setDuration] = useState(10);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [snapshotLink, setSnapshotLink] = useState<{ downloadUrl: string; sha256: string } | null>(null);
  const [diskPressure, setDiskPressure] = useState(false);
  const actionLock = useRef(false);
  const mounted = useRef(true);
  const query = useRef<AbortController | null>(null);
  const releaseLeases = useRef<() => Promise<void>>(async () => {});
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; query.current?.abort(); }; }, []);
  const videos = useRef<Record<string, HTMLVideoElement | null>>({});
  const rangeStart = utcDay(day);
  const rangeEnd = rangeStart + DAY_MS;

  useEffect(() => {
    const controller = new AbortController();
    fetchNvrStatus(controller.signal).then((status) => {
      const ids = status.cameras.map((camera) => camera.id);
      if (controller.signal.aborted) return;
      setDiskPressure(status.diskPressure);
      setAvailableIds(ids);
      setCameraIds((current) => current.length ? current.filter((id) => ids.includes(id)).slice(0, 4) : ids.slice(0, 4));
    }).catch((error: Error) => { if (!controller.signal.aborted) setNotice(error.message); });
    return () => controller.abort();
  }, []);

  const reload = useCallback(() => {
    query.current?.abort();
    if (!cameraIds.length) { setTimeline(null); setLoading(false); return; }
    const controller = new AbortController(); query.current = controller;
    setLoading(true);
    fetchNvrTimeline(rangeStart, rangeEnd, cameraIds, controller.signal)
      .then((document) => {
        if (controller.signal.aborted) return;
        setTimeline(document);
        const first = document.cameras.flatMap((camera) => camera.segments)
          .sort((left, right) => left.startUtcMs - right.startUtcMs)[0];
        setCursor((current) => current > rangeStart && current < rangeEnd ? current : clamp(first?.startUtcMs ?? rangeStart, rangeStart, rangeEnd - 1));
      })
      .catch((error: Error) => { if (!controller.signal.aborted) setNotice(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [cameraIds, rangeEnd, rangeStart]);

  useEffect(() => reload(), [reload]);

  const active = useMemo(() => timeline?.cameras.map((camera) => ({ camera, segment: playable(camera, cursor) })) ?? [], [timeline, cursor]);
  const master = active.find((entry) => entry.segment);
  const activeSegmentKey = active.flatMap((entry) => entry.segment ? [entry.segment.id] : []).join(',');

  useEffect(() => {
    let closed = false;
    let leaseIds: string[] = [];
    let inFlight: Promise<void> | null = null;
    const release = async (ids: string[]) => {
      await Promise.all(ids.map(id => releasePlaybackLease(id).catch(() => undefined)));
    };
    const renew = async () => {
      if (closed || inFlight || deleting || !activeSegmentKey) return;
      inFlight = (async () => {
        const acquired = await Promise.all(activeSegmentKey.split(',').map(id => createPlaybackLease(id, 40).catch(() => null)));
        const next = acquired.flatMap(lease => lease ? [lease.id] : []);
        if (closed) { await release(next); return; }
        const previous = leaseIds; leaseIds = next;
        await release(previous);
        if (acquired.some(lease => !lease) && mounted.current) setNotice('部分录像保护续期失败，片段可能已被清理。请刷新时间线。');
      })();
      try { await inFlight; } finally { inFlight = null; }
    };
    const stop = async () => {
      closed = true;
      await inFlight;
      const previous = leaseIds; leaseIds = []; await release(previous);
    };
    releaseLeases.current = stop;
    void renew();
    const timer = window.setInterval(() => { void renew(); }, 20_000);
    return () => { window.clearInterval(timer); void stop(); };
  }, [activeSegmentKey, deleting]);

  const seekAll = useCallback((utc: number) => {
    const next = clamp(utc, rangeStart, rangeEnd - 1);
    setCursor(next);
    timeline?.cameras.forEach((camera) => {
      const segment = playable(camera, next);
      const video = videos.current[camera.cameraId];
      if (segment && video && video.getAttribute('src') === segment.mediaUrl) video.currentTime = clamp((next - segment.startUtcMs) / 1000, 0, Math.max(0, segment.durationMs / 1000 - 0.02));
    });
  }, [rangeEnd, rangeStart, timeline]);

  const playback = useRef({ active, master, cursor });
  playback.current = { active, master, cursor };
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      const state = playback.current;
      if (!state.master?.segment) {
        const next = timeline?.cameras.flatMap(camera => camera.segments)
          .filter(segment => segment.startUtcMs > state.cursor && segment.startUtcMs < rangeEnd && !['missing', 'corrupt', 'deleted'].includes(segment.integrity))
          .sort((a, b) => a.startUtcMs - b.startUtcMs)[0];
        if (next) { seekAll(next.startUtcMs); setNotice('已跳过录像断档，恢复下一片段。'); }
        else { setPlaying(false); setNotice('已到达所选日期的录像末尾。'); }
        return;
      }
      const masterVideo = videos.current[state.master.camera.cameraId];
      if (!masterVideo || masterVideo.paused || masterVideo.readyState < 2) return;
      const globalTime = state.master.segment.startUtcMs + masterVideo.currentTime * 1000;
      setCursor(globalTime);
      state.active.forEach(({ camera, segment }) => {
        const video = videos.current[camera.cameraId];
        if (!video || !segment || video === masterVideo || video.readyState < 2) return;
        const target = (globalTime - segment.startUtcMs) / 1000;
        if (Math.abs(video.currentTime - target) > 0.25) video.currentTime = clamp(target, 0, video.duration || target);
      });
    }, 250);
    return () => window.clearInterval(timer);
  }, [playing, seekAll, timeline, rangeEnd]);

  const pauseAll = () => { ++playIntent.current; playLock.current = false; setStarting(false); setPlaying(false); Object.values(videos.current).forEach(video => video?.pause()); };
  const playVideo = async (video: HTMLVideoElement, intent: number) => {
    videoIntents.current.set(video, intent);
    await video.play();
    if (playIntent.current !== intent && videoIntents.current.get(video) === intent) video.pause();
  };
  const togglePlayback = async () => {
    if (playing || starting || playLock.current) { pauseAll(); return; }
    const intent = ++playIntent.current;
    playLock.current = true; setStarting(true);
    try {
      const players = active.flatMap(({ camera, segment }) => {
        const video = videos.current[camera.cameraId];
        return segment && video ? [video] : [];
      });
      if (!players.length) { setPlaying(true); return; }
      await Promise.all(players.map(video => { video.playbackRate = speed; return playVideo(video, intent); }));
      if (mounted.current && playIntent.current === intent) setPlaying(true);
    } catch { if (mounted.current && playIntent.current === intent) { pauseAll(); setNotice('回放未能开始，请检查片段格式、连接或浏览器声音权限后重试。'); } }
    finally { if (playIntent.current === intent) { playLock.current = false; if (mounted.current) setStarting(false); } }
  };

  const selectedSegment = master?.segment;
  const perform = async (operation: () => Promise<void>) => {
    if (actionLock.current) return;
    actionLock.current = true; setBusy(true);
    try { await operation(); }
    catch (error) { if (mounted.current) setNotice(error instanceof Error ? error.message : '操作失败'); }
    finally { actionLock.current = false; if (mounted.current) { setBusy(false); setDeleting(false); } }
  };
  const mutateSegment = (action: 'lock' | 'unlock' | 'delete') => {
    if (!selectedSegment) return;
    if (action === 'delete' && !window.confirm('删除当前片段将暂停回放，此操作不可撤销。确定继续？')) return;
    void perform(async () => {
      if (action === 'delete') {
        pauseAll(); setDeleting(true); await releaseLeases.current();
        await deleteNvrSegment(selectedSegment.id);
        if (mounted.current) setTimeline(current => current && ({ ...current, cameras: current.cameras.map(camera => ({
          ...camera, segments: camera.segments.filter(segment => segment.id !== selectedSegment.id),
        })) }));
      } else await setNvrLock(selectedSegment.id, action === 'lock');
      if (!mounted.current) return;
      setNotice(action === 'delete' ? '片段已删除并写入审计。' : `证据已${action === 'lock' ? '锁定' : '解锁'}。`);
      reload();
    });
  };
  const snapshot = () => {
    if (!selectedSegment) return;
    void perform(async () => {
      const result = await createNvrSnapshot(selectedSegment.id, Math.max(0, Math.round(cursor - selectedSegment.startUtcMs)));
      if (mounted.current) { setSnapshotLink(result); setNotice('截图已生成，可使用下方链接下载。'); }
    });
  };
  const exportClip = (mode: 'fast' | 'exact') => {
    const from = Math.round(cursor), to = Math.min(rangeEnd, from + duration * 1000);
    if (!cameraIds.length || to <= from || !Number.isInteger(duration) || duration < 1 || duration > 3600) return;
    exports.submit({ cameraIds, fromUtcMs: from, toUtcMs: to, mode, lock: true });
  };

  return (
    <div className="nvr-shell">
      <header className="nvr-header">
        <div className="brand-block"><div className="brand-mark small">W</div><div><strong>WebOBS</strong><span>NVR ARCHIVE</span></div></div>
        <div><span className="eyebrow">UTC 归档 · 时区独立显示</span><h1>时间线与证据</h1></div>
        <div className="top-actions"><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></div>
      </header>

      <section className="nvr-controls">
        <label>UTC 日期<input type="date" value={day} onChange={(event) => { if (Number.isFinite(utcDay(event.target.value))) { pauseAll(); setDay(event.target.value); setCursor(utcDay(event.target.value)); } }} /></label>
        <label>显示时区<select value={timeZone} onChange={(event) => setTimeZone(event.target.value)}>
          {[Intl.DateTimeFormat().resolvedOptions().timeZone, 'UTC', 'Asia/Shanghai', 'America/New_York', 'Europe/Berlin'].filter((value, index, values) => values.indexOf(value) === index).map((zone) => <option key={zone}>{zone}</option>)}
        </select></label>
        <div className="camera-picker" aria-label="回放摄像机">
          {availableIds.map((id) => <label key={id}><input type="checkbox" checked={cameraIds.includes(id)} disabled={!cameraIds.includes(id) && cameraIds.length >= 4} onChange={(event) => setCameraIds((current) => event.target.checked ? [...current, id].slice(0, 4) : current.filter((item) => item !== id))} />{id}</label>)}
        </div>
        <span className="nvr-query-stat">{loading ? '查询中…' : `${timeline?.queryDurationMs ?? 0} ms · ${formatTime(cursor, timeZone)}`}</span>
      </section>

      {diskPressure && <div className="alert notice-alert" role="status">录像存储空间不足，清理策略可能正在运行。请检查存储；证据导出会保留磁盘空间下限。</div>}
      {notice && <div className="alert notice-alert" role="status">{notice}</div>}

      <main className="nvr-content">
        {snapshotLink && <div className="export-result"><a href={snapshotLink.downloadUrl} download>下载最近截图</a><span>SHA-256 {snapshotLink.sha256}</span></div>}
        <section className="playback-grid" data-count={active.length}>
          {active.map(({ camera, segment }) => <article className="archive-player" key={camera.cameraId}>
            <header><strong>{camera.cameraId}</strong><span>{camera.recordedStream.toUpperCase()} · {segment?.integrity ?? 'GAP'}</span></header>
            {segment ? <video
              key={segment.id}
              ref={(node) => { videos.current[camera.cameraId] = node; }}
              src={segment.mediaUrl}
              muted={camera.cameraId !== master?.camera.cameraId}
              playsInline
              preload="metadata"
              onLoadedMetadata={(event) => {
                event.currentTarget.currentTime = clamp((cursor - segment.startUtcMs) / 1000, 0, Math.max(0, event.currentTarget.duration - 0.02));
                event.currentTarget.playbackRate = speed;
                const intent = playIntent.current;
                if (playing) void playVideo(event.currentTarget, intent).catch(() => {
                  if (mounted.current && playIntent.current === intent) { pauseAll(); setNotice('新片段播放失败，请重新点击播放或检查媒体格式。'); }
                });
              }}
              onError={() => { pauseAll(); setNotice('录像无法加载或解码，请刷新时间线并检查片段完整性。'); }}
              onEnded={() => { if (camera.cameraId === master?.camera.cameraId) seekAll(segment.endUtcMs); }}
            /> : <div className="gap-player"><strong>录像断档</strong><span>播放器将在下一片段自动恢复</span></div>}
            {segment && <img className="archive-thumb" alt="片段缩略图" src={`/api/v1/nvr/thumbnails/${segment.id}?offsetMs=${Math.min(1000, segment.durationMs - 1)}`} />}
          </article>)}
          {!active.length && <div className="nvr-empty">启用 NVR 并选择 1–4 路摄像机后查看归档。</div>}
        </section>

        <section className="transport-bar">
          <button type="button" onClick={togglePlayback}>{starting ? '取消等待播放' : playing ? '暂停' : '播放'}</button>
          <button type="button" onClick={() => { pauseAll(); seekAll(cursor + 1000 / 30); }}>逐帧 +1</button>
          <label>速度<select value={speed} onChange={(event) => { const value = Number(event.target.value); setSpeed(value); Object.values(videos.current).forEach((video) => { if (video) video.playbackRate = value; }); }}>{[0.25, 0.5, 1, 2, 4].map((value) => <option key={value} value={value}>{value}×</option>)}</select></label>
          <button type="button" disabled={!selectedSegment || busy} onClick={snapshot}>截图</button>
          <label>导出时长（秒）<input type="number" min="1" max="3600" value={duration} onChange={event => setDuration(Number(event.target.value))} /></label>
          <button type="button" disabled={!cameraIds.length || !exports.ready || !exports.allowed || exports.busy || !!exports.pending || !Number.isInteger(duration) || duration < 1 || duration > 3600} onClick={() => exportClip('fast')}>快速导出</button>
          <button type="button" disabled={!cameraIds.length || !exports.ready || !exports.allowed || exports.busy || !!exports.pending || !Number.isInteger(duration) || duration < 1 || duration > 3600} onClick={() => exportClip('exact')}>精确导出</button>
          <button type="button" disabled={!selectedSegment || busy} onClick={() => mutateSegment(selectedSegment?.locked ? 'unlock' : 'lock')}>{selectedSegment?.locked ? '解锁证据' : '锁定证据'}</button>
          <button className="danger-button" type="button" disabled={!selectedSegment || selectedSegment.locked || busy} onClick={() => mutateSegment('delete')}>删除</button>
        </section>

        <p className="nvr-help">从当前游标导出已选摄像机。快速导出保留完整片段，实际边界可能扩大；精确导出保留声音，要求每路摄像机连续录制。当前单个下载文件上限 64 MiB，较长或高码率录像请缩短导出时间。</p>
        <label className="nvr-seek">回放时间<input aria-label="回放时间游标" type="range" min={rangeStart} max={rangeEnd - 1} step="1000" value={cursor} onChange={event => seekAll(Number(event.target.value))} /></label>
        <section className="timeline-panel" onClick={(event) => { const bounds = event.currentTarget.getBoundingClientRect(); seekAll(rangeStart + clamp((event.clientX - bounds.left) / bounds.width, 0, 1) * DAY_MS); }}>
          <div className="time-ruler">{[0, 6, 12, 18, 24].map((hour) => <span key={hour} style={{ left: `${hour / 24 * 100}%` }}>{String(hour).padStart(2, '0')}:00</span>)}</div>
          {timeline?.cameras.map((camera) => <div className="timeline-track" key={camera.cameraId}>
            <strong>{camera.cameraId}</strong>
            <div className="track-rail">
              {camera.segments.map((segment) => <i key={segment.id} className={`segment-block kind-${segment.kind} integrity-${segment.integrity}`} style={{ left: `${(segment.startUtcMs - rangeStart) / DAY_MS * 100}%`, width: `${Math.max(.08, segment.durationMs / DAY_MS * 100)}%` }} title={`${segment.kind} · ${segment.integrity}`} />)}
              {camera.gaps.map((gap, index) => <i key={`${gap.fromUtcMs}-${index}`} className={`gap-block reason-${gap.reason}`} style={{ left: `${(gap.fromUtcMs - rangeStart) / DAY_MS * 100}%`, width: `${Math.max(.08, (gap.toUtcMs - gap.fromUtcMs) / DAY_MS * 100)}%` }} title={`断档：${gap.reason}`} />)}
            </div>
          </div>)}
          <div className="playhead" style={{ left: `${(cursor - rangeStart) / DAY_MS * 100}%` }} />
        </section>

        <NvrExportPanel exports={exports} />
      </main>
    </div>
  );
}
