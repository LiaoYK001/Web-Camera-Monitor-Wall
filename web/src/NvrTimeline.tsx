import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createNvrExport,
  createNvrSnapshot,
  createPlaybackLease,
  deleteNvrSegment,
  fetchNvrStatus,
  fetchNvrTimeline,
  setNvrLock,
  releasePlaybackLease,
} from './api';
import type { NvrExport, NvrSegment, NvrTimeline as TimelineDocument, NvrTimelineCamera } from './types';

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
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [latestExport, setLatestExport] = useState<NvrExport | null>(null);
  const videos = useRef<Record<string, HTMLVideoElement | null>>({});
  const rangeStart = utcDay(day);
  const rangeEnd = rangeStart + DAY_MS;

  useEffect(() => {
    const controller = new AbortController();
    fetchNvrStatus(controller.signal).then((status) => {
      const ids = status.cameras.map((camera) => camera.id);
      setAvailableIds(ids);
      setCameraIds((current) => current.length ? current.filter((id) => ids.includes(id)).slice(0, 4) : ids.slice(0, 4));
    }).catch((error: Error) => setNotice(error.message));
    return () => controller.abort();
  }, []);

  const reload = useCallback(() => {
    if (!cameraIds.length) { setTimeline(null); setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    fetchNvrTimeline(rangeStart, rangeEnd, cameraIds, controller.signal)
      .then((document) => {
        setTimeline(document);
        const first = document.cameras.flatMap((camera) => camera.segments)
          .sort((left, right) => left.startUtcMs - right.startUtcMs)[0];
        setCursor((current) => current >= rangeStart && current < rangeEnd ? current : first?.startUtcMs ?? rangeStart);
        setNotice('');
      })
      .catch((error: Error) => setNotice(error.message))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [cameraIds, rangeEnd, rangeStart]);

  useEffect(() => reload(), [reload]);

  const active = useMemo(() => timeline?.cameras.map((camera) => ({ camera, segment: playable(camera, cursor) })) ?? [], [timeline, cursor]);
  const master = active.find((entry) => entry.segment);
  const activeSegmentKey = active.flatMap((entry) => entry.segment ? [entry.segment.id] : []).join(',');

  useEffect(() => {
    let closed = false;
    let leaseIds: string[] = [];
    const renew = async () => {
      const previous = leaseIds;
      leaseIds = [];
      await Promise.all(previous.map((id) => releasePlaybackLease(id).catch(() => undefined)));
      if (closed || !activeSegmentKey) return;
      const acquired = await Promise.all(activeSegmentKey.split(',').map((id) => createPlaybackLease(id, 30).catch(() => null)));
      if (closed) {
        await Promise.all(acquired.flatMap((lease) => lease ? [releasePlaybackLease(lease.id).catch(() => undefined)] : []));
      } else leaseIds = acquired.flatMap((lease) => lease ? [lease.id] : []);
    };
    void renew();
    const timer = window.setInterval(() => { void renew(); }, 20_000);
    return () => {
      closed = true;
      window.clearInterval(timer);
      leaseIds.forEach((id) => { void releasePlaybackLease(id).catch(() => undefined); });
    };
  }, [activeSegmentKey]);

  const seekAll = useCallback((utc: number) => {
    const next = clamp(utc, rangeStart, rangeEnd - 1);
    setCursor(next);
    timeline?.cameras.forEach((camera) => {
      const segment = playable(camera, next);
      const video = videos.current[camera.cameraId];
      if (segment && video) video.currentTime = clamp((next - segment.startUtcMs) / 1000, 0, Math.max(0, segment.durationMs / 1000 - 0.02));
    });
  }, [rangeEnd, rangeStart, timeline]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!playing || !master?.segment) return;
      const masterVideo = videos.current[master.camera.cameraId];
      if (!masterVideo) return;
      const globalTime = master.segment.startUtcMs + masterVideo.currentTime * 1000;
      setCursor(globalTime);
      active.forEach(({ camera, segment }) => {
        const video = videos.current[camera.cameraId];
        if (!video || !segment || video === masterVideo) return;
        const target = (globalTime - segment.startUtcMs) / 1000;
        if (Math.abs(video.currentTime - target) > 0.25) video.currentTime = clamp(target, 0, video.duration || target);
      });
    }, 250);
    return () => window.clearInterval(timer);
  }, [active, master, playing]);

  const togglePlayback = async () => {
    const next = !playing;
    setPlaying(next);
    await Promise.all(active.map(async ({ camera, segment }) => {
      const video = videos.current[camera.cameraId];
      if (!video || !segment) return;
      video.playbackRate = speed;
      if (next) await video.play().catch(() => undefined); else video.pause();
    }));
  };

  const selectedSegment = master?.segment;
  const mutateSegment = async (action: 'lock' | 'unlock' | 'delete') => {
    if (!selectedSegment) return;
    try {
      if (action === 'delete') {
        if (!window.confirm('确定删除当前未锁定片段？此操作不可撤销。')) return;
        await deleteNvrSegment(selectedSegment.id);
      } else await setNvrLock(selectedSegment.id, action === 'lock');
      setNotice(action === 'delete' ? '片段已删除并写入审计。' : `证据已${action === 'lock' ? '锁定' : '解锁'}。`);
      reload();
    } catch (error) { setNotice(error instanceof Error ? error.message : '操作失败'); }
  };

  const snapshot = async () => {
    if (!selectedSegment) return;
    try {
      const result = await createNvrSnapshot(selectedSegment.id, Math.max(0, cursor - selectedSegment.startUtcMs));
      setNotice(`截图已生成，SHA-256 ${result.sha256.slice(0, 12)}…`);
      window.open(result.downloadUrl, '_blank', 'noopener,noreferrer');
    } catch (error) { setNotice(error instanceof Error ? error.message : '截图失败'); }
  };

  const exportClip = async (mode: 'fast' | 'exact') => {
    if (!selectedSegment) return;
    const end = Math.min(selectedSegment.endUtcMs, cursor + 10_000);
    if (end <= cursor) return;
    try {
      setNotice('正在生成证据导出…');
      const result = await createNvrExport(cameraIds, cursor, end, mode);
      setLatestExport(result);
      setNotice(`${mode === 'fast' ? '快速' : '精确'}导出完成，审计 ID ${result.auditId.slice(0, 12)}…`);
    } catch (error) { setNotice(error instanceof Error ? error.message : '导出失败'); }
  };

  return (
    <div className="nvr-shell">
      <header className="nvr-header">
        <div className="brand-block"><div className="brand-mark small">W</div><div><strong>WebOBS</strong><span>NVR ARCHIVE</span></div></div>
        <div><span className="eyebrow">UTC 归档 · 时区独立显示</span><h1>时间线与证据</h1></div>
        <div className="top-actions"><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></div>
      </header>

      <section className="nvr-controls">
        <label>UTC 日期<input type="date" value={day} onChange={(event) => { setDay(event.target.value); setCursor(utcDay(event.target.value)); }} /></label>
        <label>显示时区<select value={timeZone} onChange={(event) => setTimeZone(event.target.value)}>
          {[Intl.DateTimeFormat().resolvedOptions().timeZone, 'UTC', 'Asia/Shanghai', 'America/New_York', 'Europe/Berlin'].filter((value, index, values) => values.indexOf(value) === index).map((zone) => <option key={zone}>{zone}</option>)}
        </select></label>
        <div className="camera-picker" aria-label="回放摄像机">
          {availableIds.map((id) => <label key={id}><input type="checkbox" checked={cameraIds.includes(id)} onChange={(event) => setCameraIds((current) => event.target.checked ? [...current, id].slice(-4) : current.filter((item) => item !== id))} />{id}</label>)}
        </div>
        <span className="nvr-query-stat">{loading ? '查询中…' : `${timeline?.queryDurationMs ?? 0} ms · ${formatTime(cursor, timeZone)}`}</span>
      </section>

      {notice && <div className="alert notice-alert" role="status">{notice}</div>}

      <main className="nvr-content">
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
              onLoadedMetadata={(event) => { event.currentTarget.currentTime = clamp((cursor - segment.startUtcMs) / 1000, 0, Math.max(0, event.currentTarget.duration - 0.02)); event.currentTarget.playbackRate = speed; }}
              onEnded={() => seekAll(segment.endUtcMs + 1)}
            /> : <div className="gap-player"><strong>录像断档</strong><span>播放器将在下一片段自动恢复</span></div>}
            {segment && <img className="archive-thumb" alt="片段缩略图" src={`/api/v1/nvr/thumbnails/${segment.id}?offsetMs=${Math.min(1000, segment.durationMs - 1)}`} />}
          </article>)}
          {!active.length && <div className="nvr-empty">启用 NVR 并选择 1–4 路摄像机后查看归档。</div>}
        </section>

        <section className="transport-bar">
          <button type="button" onClick={togglePlayback}>{playing ? '暂停' : '播放'}</button>
          <button type="button" onClick={() => { setPlaying(false); active.forEach(({ camera }) => videos.current[camera.cameraId]?.pause()); seekAll(cursor + 1000 / 30); }}>逐帧 +1</button>
          <label>速度<select value={speed} onChange={(event) => { const value = Number(event.target.value); setSpeed(value); Object.values(videos.current).forEach((video) => { if (video) video.playbackRate = value; }); }}>{[0.25, 0.5, 1, 2, 4].map((value) => <option key={value} value={value}>{value}×</option>)}</select></label>
          <button type="button" disabled={!selectedSegment} onClick={snapshot}>截图</button>
          <button type="button" disabled={!selectedSegment} onClick={() => exportClip('fast')}>快速导出 10 秒</button>
          <button type="button" disabled={!selectedSegment} onClick={() => exportClip('exact')}>精确导出 10 秒</button>
          <button type="button" disabled={!selectedSegment} onClick={() => mutateSegment(selectedSegment?.locked ? 'unlock' : 'lock')}>{selectedSegment?.locked ? '解锁证据' : '锁定证据'}</button>
          <button className="danger-button" type="button" disabled={!selectedSegment || selectedSegment.locked} onClick={() => mutateSegment('delete')}>删除</button>
        </section>

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

        {latestExport && <section className="export-result"><strong>证据清单</strong><span>SHA-256 {latestExport.manifestSha256}</span><a href={latestExport.manifestUrl} target="_blank" rel="noreferrer">下载 manifest</a>{latestExport.files.map((file) => <a key={file.name} href={file.downloadUrl}>{file.cameraId} · {file.sha256.slice(0, 12)}…</a>)}</section>}
      </main>
    </div>
  );
}
