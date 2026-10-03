import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNvrExportJobs } from './useNvrExportJobs';
import { NvrExportPanel } from './NvrExportPanel';
import { archiveError, useNvrArchiveQuery } from './useNvrArchiveQuery';
import { withRequestTimeout } from './requestTimeout';
import { useMonitorPreferences } from './useMonitorPreferences';
import { isPageVisible, subscribePageVisibility } from './pageVisibility';
import {
  createNvrSnapshot,
  createPlaybackLease,
  deleteNvrSegment,
  setNvrLock,
  releasePlaybackLease,
} from './api';
import type { NvrSegment, NvrTimelineCamera } from './types';

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
  const [cursor, setCursor] = useState(utcDay(todayUtc()));
  const [speed, setSpeed] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [starting, setStarting] = useState(false);
  const playIntent = useRef(0);
  const playLock = useRef(false);
  const videoIntents = useRef(new WeakMap<HTMLVideoElement, number>());
  const [notice, setNotice] = useState('');
  const exports = useNvrExportJobs();
  const audio = useMonitorPreferences(false, false, true);
  const [duration, setDuration] = useState(10);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [snapshotLink, setSnapshotLink] = useState<{ downloadUrl: string; sha256: string } | null>(null);
  const actionLock = useRef(false);
  const mounted = useRef(true);
  const lifecycle = useRef<AbortController | null>(null);
  const releaseLeases = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    const owner = new AbortController(); lifecycle.current = owner; mounted.current = true;
    return () => { mounted.current = false; ++playIntent.current; owner.abort(); };
  }, []);
  const videos = useRef<Record<string, HTMLVideoElement | null>>({});
  const rangeStart = utcDay(day);
  const rangeEnd = rangeStart + DAY_MS;
  const archive = useNvrArchiveQuery(rangeStart, rangeEnd);
  const { cameraIds, setCameraIds, availableIds, diskPressure, timeline, loading, reload } = archive;

  useEffect(() => {
    if (!timeline) return;
    const first = timeline.cameras.flatMap(camera => camera.segments)
      .filter(segment => !['missing', 'corrupt', 'deleted'].includes(segment.integrity))
      .sort((left, right) => left.startUtcMs - right.startUtcMs)[0];
    setCursor(current => current > rangeStart && current < rangeEnd ? current
      : clamp(first?.startUtcMs ?? rangeStart, rangeStart, rangeEnd - 1));
  }, [timeline, rangeStart, rangeEnd]);

  const active = useMemo(() => timeline?.cameras.map((camera) => ({ camera, segment: playable(camera, cursor) })) ?? [], [timeline, cursor]);
  const master = active.find((entry) => entry.segment);
  const audioCameraId = audio.view.archiveAudioCameraId ?? active.find(entry =>
    entry.segment?.audioCodec && entry.segment.audioCodec !== 'none')?.camera.cameraId;
  const audioSegment = active.find(entry => entry.camera.cameraId === audioCameraId)?.segment;
  const audioRequested = audio.loaded && audio.view.audioMonitorEnabled && audio.view.audioOutput === 'speaker';
  const audioAvailable = !!audioSegment && !!audioSegment.audioCodec && audioSegment.audioCodec !== 'none';
  const activeSegmentKey = active.flatMap((entry) => entry.segment ? [entry.segment.id] : []).join(',');
  useEffect(() => {
    Object.values(videos.current).forEach(video => { if (video) video.volume = audio.loaded ? audio.view.localMonitorVolume : 0; });
  }, [audio.loaded, audio.view.localMonitorVolume, activeSegmentKey]);

  useEffect(() => {
    let closed = false;
    let leaseIds: string[] = [];
    let inFlight: Promise<void> | null = null;
    const release = async (ids: string[]) => {
      await Promise.all(ids.map(id => withRequestTimeout(8000, signal => releasePlaybackLease(id, signal)).catch(() => undefined)));
    };
    const renew = async () => {
      if (closed || inFlight || deleting || !activeSegmentKey || !isPageVisible()) return;
      inFlight = (async () => {
        const acquired = await Promise.all(activeSegmentKey.split(',').map(id =>
          withRequestTimeout(8000, signal => createPlaybackLease(id, 40, signal)).catch(() => null)));
        const next = acquired.flatMap(lease => lease ? [lease.id] : []);
        if (closed || !isPageVisible()) { await release(next); return; }
        const previous = leaseIds; leaseIds = next;
        await release(previous);
        if (!closed && acquired.some(lease => !lease) && mounted.current) setNotice('部分录像保护续期失败，片段可能已被清理。请刷新时间线。');
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
    const visible = subscribePageVisibility(() => { if (isPageVisible()) void renew(); });
    return () => { window.clearInterval(timer); visible(); void stop(); };
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

  const pauseAll = useCallback(() => { ++playIntent.current; playLock.current = false; setStarting(false); setPlaying(false); Object.values(videos.current).forEach(video => video?.pause()); }, []);
  useEffect(() => { pauseAll(); }, [archive.selectionKey, pauseAll]);
  useEffect(() => subscribePageVisibility(() => { if (!isPageVisible()) pauseAll(); }), [pauseAll]);
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
  const perform = async (operation: (signal: AbortSignal) => Promise<void>) => {
    if (actionLock.current) return;
    const owner = lifecycle.current;
    if (!owner || owner.signal.aborted) return;
    actionLock.current = true; setBusy(true);
    try { await withRequestTimeout(35_000, operation, owner.signal); }
    catch (error) { if (!owner.signal.aborted) setNotice(error instanceof Error && error.name === 'TimeoutError'
      ? '操作超时，结果尚未确认。请刷新时间线核对后再操作；截图可稍后重新生成。'
      : archiveError(error)); }
    finally { actionLock.current = false; if (mounted.current) { setBusy(false); setDeleting(false); } }
  };
  const mutateSegment = (action: 'lock' | 'unlock' | 'delete') => {
    if (!selectedSegment || actionLock.current) return;
    if (action === 'delete' && !window.confirm('删除当前片段将暂停回放，此操作不可撤销。确定继续？')) return;
    void perform(async signal => {
      if (action === 'delete') {
        pauseAll(); setDeleting(true); await releaseLeases.current();
        if (signal.aborted) throw signal.reason;
        await deleteNvrSegment(selectedSegment.id, signal);
      } else await setNvrLock(selectedSegment.id, action === 'lock', signal);
      if (!mounted.current) return;
      setNotice(action === 'delete' ? '片段已删除并写入审计。' : `证据已${action === 'lock' ? '锁定' : '解锁'}。`);
      reload();
    });
  };
  const snapshot = () => {
    if (!selectedSegment) return;
    void perform(async signal => {
      const result = await createNvrSnapshot(selectedSegment.id, Math.max(0, Math.round(cursor - selectedSegment.startUtcMs)), signal);
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
        <label>UTC 日期<input type="date" value={day} disabled={busy} onChange={(event) => { if (Number.isFinite(utcDay(event.target.value))) { pauseAll(); setNotice(''); setDay(event.target.value); setCursor(utcDay(event.target.value)); } }} /></label>
        <label>显示时区<select value={timeZone} onChange={(event) => setTimeZone(event.target.value)}>
          {[Intl.DateTimeFormat().resolvedOptions().timeZone, 'UTC', 'Asia/Shanghai', 'America/New_York', 'Europe/Berlin'].filter((value, index, values) => values.indexOf(value) === index).map((zone) => <option key={zone}>{zone}</option>)}
        </select></label>
        <div className="camera-picker" aria-label="回放摄像机">
          {availableIds.map((id) => <label key={id}><input type="checkbox" checked={cameraIds.includes(id)} disabled={busy || (!cameraIds.includes(id) && cameraIds.length >= 4)} onChange={(event) => { pauseAll(); setNotice(''); setCameraIds((current) => event.target.checked ? [...current, id].slice(0, 4) : current.filter((item) => item !== id)); }} />{id}</label>)}
        </div>
        <button type="button" disabled={busy || loading || archive.catalogLoading} onClick={() => { pauseAll(); setNotice(''); archive.reloadCatalog(); reload(); }}>刷新时间线</button>
        <span className="nvr-query-stat" role="status">{loading || archive.catalogLoading ? '查询中…' : timeline ? `${timeline.queryDurationMs} ms · ${formatTime(cursor, timeZone)}` : '暂无可用时间线'}</span>
      </section>

      {archive.catalogError && <div className="alert notice-alert" role="alert">无法读取回放摄像机：{archive.catalogError}<button type="button" onClick={archive.reloadCatalog} disabled={archive.catalogLoading}>重试摄像机列表</button></div>}
      {archive.error && <div className="alert notice-alert" role="alert">时间线查询失败：{archive.error}<button type="button" onClick={reload} disabled={loading || busy}>重试时间线</button></div>}
      {diskPressure && <div className="alert notice-alert" role="status">录像存储空间不足，清理策略可能正在运行。请检查存储；证据导出会保留磁盘空间下限。</div>}
      {notice && <div className="alert notice-alert" role="status">{notice}</div>}

      <main className="nvr-content">
        <fieldset className="nvr-audio-controls" disabled={!audio.loaded}>
          <legend>归档声音</legend>
          <label><input type="checkbox" checked={audio.view.audioMonitorEnabled} onChange={event => audio.setView(view => ({ ...view, audioMonitorEnabled: event.target.checked }))} />启用声音监听</label>
          <label>声音输出<select aria-label="归档声音输出" value={audio.view.audioOutput} onChange={event => audio.setView(view => ({ ...view, audioOutput: event.target.value as 'speaker' | 'meter-only' }))}>
            <option value="speaker">扬声器</option><option value="meter-only">静音（实时监控保留电平检测）</option>
          </select></label>
          <label>主音量<input aria-label="归档监听主音量" type="range" min="0" max="1" step="0.01" value={audio.view.localMonitorVolume} onChange={event => audio.setView(view => ({ ...view, localMonitorVolume: Number(event.target.value) }))} /></label>
          <label>声音摄像机<select aria-label="归档声音摄像机" value={audio.view.archiveAudioCameraId ?? ''} onChange={event => audio.setView(view => ({ ...view, archiveAudioCameraId: event.target.value || null }))}>
            <option value="">自动（第一路有音轨的录像）</option>
            {audio.view.archiveAudioCameraId && !cameraIds.includes(audio.view.archiveAudioCameraId) && <option value={audio.view.archiveAudioCameraId}>{audio.view.archiveAudioCameraId}（当前未显示）</option>}
            {cameraIds.map(id => <option key={id} value={id}>{id}</option>)}
          </select></label>
          <span role="status">{!audio.loaded ? audio.error ? '声音偏好暂不可用，保持静音' : '正在读取账号声音偏好…' : !audio.view.audioMonitorEnabled ? '声音监听已关闭' : audio.view.audioOutput === 'meter-only' ? '归档扬声器输出已静音'
            : !audioAvailable ? '声音摄像机当前无可用音轨，保持静音' : `监听 ${audioCameraId} · ${Math.round(audio.view.localMonitorVolume * 100)}%`}</span>
          <p>监听开关、声音输出和主音量与实时监控共享账号设置；选择的声音摄像机也会保存。静音和音量只影响客户端监听，原录像与导出音轨保留。</p>
        </fieldset>
        {audio.error && <div className="alert notice-alert" role="alert">{audio.error}<button type="button" onClick={audio.retry}>重试声音偏好</button></div>}
        {snapshotLink && <div className="export-result"><a href={snapshotLink.downloadUrl} download>下载最近截图</a><span>SHA-256 {snapshotLink.sha256}</span></div>}
        <section className="playback-grid" data-count={active.length} aria-busy={loading || archive.catalogLoading}>
          {active.map(({ camera, segment }) => <article className="archive-player" key={camera.cameraId}>
            <header><strong>{camera.cameraId}</strong><span>{camera.recordedStream.toUpperCase()} · {segment?.integrity ?? 'GAP'}</span></header>
            {segment && !deleting ? <video
              key={segment.id}
              ref={(node) => { videos.current[camera.cameraId] = node; }}
              src={segment.mediaUrl}
              muted={!audioRequested || !audioAvailable || camera.cameraId !== audioCameraId}
              playsInline
              preload="metadata"
              onLoadedMetadata={(event) => {
                event.currentTarget.currentTime = clamp((cursor - segment.startUtcMs) / 1000, 0, Math.max(0, event.currentTarget.duration - 0.02));
                event.currentTarget.playbackRate = speed;
                event.currentTarget.volume = audio.loaded ? audio.view.localMonitorVolume : 0;
                const intent = playIntent.current;
                if (playing) void playVideo(event.currentTarget, intent).catch(() => {
                  if (mounted.current && playIntent.current === intent) { pauseAll(); setNotice('新片段播放失败，请重新点击播放或检查媒体格式。'); }
                });
              }}
              onError={() => { pauseAll(); setNotice('录像无法加载或解码，请刷新时间线并检查片段完整性。'); }}
              onEnded={() => { if (camera.cameraId === master?.camera.cameraId) seekAll(segment.endUtcMs); }}
            /> : <div className="gap-player"><strong>{deleting ? '正在释放回放保护…' : '录像断档'}</strong><span>{deleting ? '确认删除后将刷新时间线' : '播放器将在下一片段自动恢复'}</span></div>}
            {segment && <img className="archive-thumb" alt="片段缩略图" src={`/api/v1/nvr/thumbnails/${segment.id}?offsetMs=${Math.min(1000, segment.durationMs - 1)}`} />}
          </article>)}
          {!active.length && <div className="nvr-empty">{loading || archive.catalogLoading ? '正在读取所选日期的录像…'
            : archive.error || archive.catalogError ? '查询未完成，请使用上方重试按钮。'
            : availableIds.length ? '选择 1–4 路摄像机查看归档。' : '暂无可回放摄像机。请先在设置中配置 NVR 录像。'}</div>}
        </section>

        <section className="transport-bar">
          <button type="button" disabled={(!timeline || loading || busy) && !playing && !starting} onClick={togglePlayback}>{starting ? '取消等待播放' : playing ? '暂停' : '播放'}</button>
          <button type="button" disabled={!timeline || loading || busy} onClick={() => { pauseAll(); seekAll(cursor + 1000 / 30); }}>前进 1/30 秒</button>
          <label>速度<select value={speed} onChange={(event) => { const value = Number(event.target.value); setSpeed(value); Object.values(videos.current).forEach((video) => { if (video) video.playbackRate = value; }); }}>{[0.25, 0.5, 1, 2, 4].map((value) => <option key={value} value={value}>{value}×</option>)}</select></label>
          <button type="button" disabled={!selectedSegment || busy} onClick={snapshot}>截图</button>
          <label>导出时长（秒）<input type="number" min="1" max="3600" value={duration} onChange={event => setDuration(Number(event.target.value))} /></label>
          <button type="button" disabled={!timeline || loading || !cameraIds.length || !exports.ready || !exports.allowed || exports.busy || !!exports.pending || !Number.isInteger(duration) || duration < 1 || duration > 3600} onClick={() => exportClip('fast')}>快速导出</button>
          <button type="button" disabled={!timeline || loading || !cameraIds.length || !exports.ready || !exports.allowed || exports.busy || !!exports.pending || !Number.isInteger(duration) || duration < 1 || duration > 3600} onClick={() => exportClip('exact')}>精确导出</button>
          <button type="button" disabled={!selectedSegment || busy} onClick={() => mutateSegment(selectedSegment?.locked ? 'unlock' : 'lock')}>{selectedSegment?.locked ? '解锁证据' : '锁定证据'}</button>
          <button className="danger-button" type="button" disabled={!selectedSegment || selectedSegment.locked || busy} onClick={() => mutateSegment('delete')}>删除</button>
        </section>

        <p className="nvr-help">从当前游标导出已选摄像机。快速导出保留完整片段，实际边界可能扩大；精确导出保留声音，要求每路摄像机连续录制。大文件按块下载，导出前会检查磁盘余量。支持从游标向后导出最多 1 小时；需要更长范围时请分次导出。</p>
        <label className="nvr-seek">回放时间<input aria-label="回放时间游标" type="range" disabled={!timeline || loading || busy} min={rangeStart} max={rangeEnd - 1} step="1000" value={cursor} onChange={event => seekAll(Number(event.target.value))} /></label>
        <section className="timeline-panel" aria-label="UTC 录像时间线" onClick={(event) => {
          if (!timeline || loading || busy || !(event.target instanceof Element)) return;
          const rail = event.target.closest('.track-rail, .time-ruler');
          if (!rail) return;
          const bounds = rail.getBoundingClientRect();
          if (bounds.width > 0) seekAll(rangeStart + clamp((event.clientX - bounds.left) / bounds.width, 0, 1) * DAY_MS);
        }}>
          <div className="time-ruler" title="UTC 时间刻度">{[0, 6, 12, 18, 24].map((hour) => <span key={hour} style={{ left: `${hour / 24 * 100}%` }}>{String(hour).padStart(2, '0')}:00</span>)}</div>
          {timeline?.cameras.map((camera) => <div className="timeline-track" key={camera.cameraId}>
            <strong>{camera.cameraId}</strong>
            <div className="track-rail">
              {camera.segments.map((segment) => <i key={segment.id} className={`segment-block kind-${segment.kind} integrity-${segment.integrity}`} style={{ left: `${(segment.startUtcMs - rangeStart) / DAY_MS * 100}%`, width: `${Math.max(.08, segment.durationMs / DAY_MS * 100)}%` }} title={`${segment.kind} · ${segment.integrity}`} />)}
              {camera.gaps.map((gap, index) => <i key={`${gap.fromUtcMs}-${index}`} className={`gap-block reason-${gap.reason}`} style={{ left: `${(gap.fromUtcMs - rangeStart) / DAY_MS * 100}%`, width: `${Math.max(.08, (gap.toUtcMs - gap.fromUtcMs) / DAY_MS * 100)}%` }} title={`断档：${gap.reason}`} />)}
            </div>
          </div>)}
          <div className="timeline-playhead-rail"><div className="playhead" style={{ left: `${(cursor - rangeStart) / DAY_MS * 100}%` }} /></div>
        </section>

        <NvrExportPanel exports={exports} />
      </main>
    </div>
  );
}
