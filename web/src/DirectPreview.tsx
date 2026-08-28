import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react';
import { fetchAnalyticsPolicies, fetchCameras, fetchPlaybackCapabilities } from './api';
import { activateGateway, approvedBrowserProfile, BrowserPlanError, browserGrantProfile, connectApprovedWhep, connectHls, connectMjpeg, offlineSignedGrantPlan, requestBrowserPlan, type BrowserTopologyPlan } from './browserMedia';
import { DirectAudioMixer, type DirectAudioSnapshot } from './directAudioMixer';
import { clearPrivateRuntimeState, loadMonitorView, saveMonitorView } from './localRuntime';
import { formatTelemetry, sampleConnectionTelemetry, sampleElementTelemetry, unavailableTelemetry, type MediaTelemetry } from './mediaTelemetry';
import { applyAutomaticLayout, defaultMonitorView, nextRotationWindow, normalizeMonitorView, selectLowPowerProfile, validDetectionSignal, type DetectionSignal, type MonitorView, type TelemetryOverlayConfig } from './monitorView';
import type { AnalyticsPolicy, CameraRecord, CameraSceneSource, SceneDocument, SceneItem, SceneSource, SourcePlaybackCapability } from './types';
import { connectSource, type ProgramConnection, type ProgramConnectionState } from './whep';

const labels: Record<ProgramConnectionState, string> = {
  checking: '检查中',
  connecting: '连接中',
  live: '直达',
  reconnecting: '重连中',
  offline: '离线',
  disabled: '未启用',
};

function videoGeometry(item: SceneItem, width: number, height: number): CSSProperties {
  if (width <= 0 || height <= 0) return { width: '100%', height: '100%', objectFit: item.scaleMode === 'stretch' ? 'fill' : item.scaleMode };
  const croppedWidth = Math.max(1, width - item.crop.left - item.crop.right);
  const croppedHeight = Math.max(1, height - item.crop.top - item.crop.bottom);
  const scaleX = item.width / croppedWidth;
  const scaleY = item.height / croppedHeight;
  const scale = item.scaleMode === 'contain' ? Math.min(scaleX, scaleY)
    : item.scaleMode === 'cover' ? Math.max(scaleX, scaleY) : 1;
  const renderedWidth = item.scaleMode === 'stretch' ? width * scaleX : width * scale;
  const renderedHeight = item.scaleMode === 'stretch' ? height * scaleY : height * scale;
  const contentWidth = item.scaleMode === 'stretch' ? item.width : croppedWidth * scale;
  const contentHeight = item.scaleMode === 'stretch' ? item.height : croppedHeight * scale;
  const left = (item.width - contentWidth) / 2 - item.crop.left * (item.scaleMode === 'stretch' ? scaleX : scale);
  const top = (item.height - contentHeight) / 2 - item.crop.top * (item.scaleMode === 'stretch' ? scaleY : scale);
  return {
    width: `${(renderedWidth / item.width) * 100}%`,
    height: `${(renderedHeight / item.height) * 100}%`,
    left: `${(left / item.width) * 100}%`,
    top: `${(top / item.height) * 100}%`,
  };
}

function DirectTile({ item, source, capability, mixer }: {
  item: SceneItem;
  source: SceneSource;
  capability?: SourcePlaybackCapability;
  mixer: DirectAudioMixer | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<ProgramConnectionState>(capability ? 'checking' : 'offline');
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (source.kind === 'camera' || !videoRef.current || !mixer || !capability?.endpoint || capability.preferred !== 'direct') return undefined;
    const connection = connectSource(videoRef.current, capability.endpoint, setState,
      (stream) => mixer.bindStream(source.id, stream));
    return connection.close;
  }, [capability, mixer, source.id]);

  useEffect(() => {
    if (source.kind === 'camera' || !mixer || !videoRef.current || !capability?.endpoint || capability.preferred !== 'direct') return undefined;
    return mixer.attach(source.id, videoRef.current);
  }, [capability, mixer, source.id]);

  const geometry = useMemo(
    () => videoGeometry(item, dimensions.width, dimensions.height),
    [item, dimensions],
  );

  if (source.kind === 'camera') return null;

  return (
    <div
      className={`direct-tile ${state}`}
      data-source-id={source.id}
      data-audio-gain={source.muted ? '0' : source.volume.toFixed(3)}
      data-audio-sync-ms={source.syncOffsetMs}
    >
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        style={geometry}
        aria-label={`${source.name} 网关直通画面`}
        onLoadedMetadata={(event) => setDimensions({
          width: event.currentTarget.videoWidth,
          height: event.currentTarget.videoHeight,
        })}
      />
      <span className="direct-tile-state"><i aria-hidden="true" />{labels[state]}</span>
      {capability && capability.strategy !== 'unknown' && (
        <div className={`delivery-diagnostic cost-${capability.serverCost ?? 'low'}`}>
          <strong>{capability.deliveryMode === 'hybrid' ? 'HYBRID' : 'DIRECT RELAY'}</strong>
          <span>Video: {capability.videoDelivery ?? 'copy'} · Audio: {capability.audioDelivery ?? 'copy'}</span>
          <span>Server decode: {capability.serverVideoDecode ? 'ON' : 'OFF'} · encode: {capability.encoder ?? 'none'}</span>
          {capability.reason && <span>Reason: {capability.reason}</span>}
        </div>
      )}
      {source.kind === 'browser'
        ? <span className="direct-tile-name">{source.name} · 仅服务端合成</span>
        : state !== 'live' && <span className="direct-tile-name">{source.name}</span>}
    </div>
  );
}

function TelemetryOverlay({ config, transport, video, connection }: {
  config: TelemetryOverlayConfig;
  transport: 'whep' | 'hls' | 'mjpeg' | 'gateway';
  video: HTMLVideoElement | null;
  connection: ProgramConnection | null;
}) {
  const [value, setValue] = useState<MediaTelemetry>(unavailableTelemetry());
  useEffect(() => {
    if (!config.enabled) return undefined;
    let closed = false;
    let previous: { at: number; frames: number; bytes: number } | undefined;
    const sample = async () => {
      if (closed || !connection) { setValue(unavailableTelemetry()); return; }
      if (transport === 'mjpeg') { setValue({ ...unavailableTelemetry(), codec: 'MJPEG' }); return; }
      try {
        const result = connection.getStats
          ? await sampleConnectionTelemetry(connection, previous)
          : video ? sampleElementTelemetry(video, connection, previous) : { telemetry: unavailableTelemetry() };
        if (!closed) { setValue(result.telemetry); previous = result.previous; }
      } catch { if (!closed) setValue(unavailableTelemetry()); }
    };
    void sample();
    const timer = window.setInterval(() => void sample(), config.refreshIntervalMs);
    return () => { closed = true; window.clearInterval(timer); };
  }, [config.enabled, config.refreshIntervalMs, connection, transport, video]);
  if (!config.enabled) return null;
  const custom = config.position === 'custom' ? { left: `${config.customX * 100}%`, top: `${config.customY * 100}%` } : undefined;
  return <div className={`telemetry-overlay position-${config.position}`} style={{
    ...custom, color: `rgba(255,255,255,${config.textOpacity})`,
    backgroundColor: config.backgroundEnabled ? colorWithOpacity(config.backgroundColor, config.backgroundOpacity) : 'transparent',
  }} data-telemetry-transport={transport} aria-live="off">
    {formatTelemetry(value, config.fields)}
  </div>;
}

function colorWithOpacity(color: string, opacity: number): string {
  const red = Number.parseInt(color.slice(1, 3), 16);
  const green = Number.parseInt(color.slice(3, 5), 16);
  const blue = Number.parseInt(color.slice(5, 7), 16);
  return `rgba(${red},${green},${blue},${opacity})`;
}

function BrowserCameraTile({ item, source, mixer, telemetry, lowPower, playbackEnabled }: {
  item: SceneItem;
  source: CameraSceneSource;
  mixer: DirectAudioMixer | null;
  telemetry: TelemetryOverlayConfig;
  lowPower?: { targetFps: number; actualFps: number; targetMet: boolean };
  playbackEnabled: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [state, setState] = useState<ProgramConnectionState>('checking');
  const [transport, setTransport] = useState<'whep' | 'hls' | 'mjpeg' | 'gateway'>('gateway');
  const [plan, setPlan] = useState<BrowserTopologyPlan | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [activeConnection, setActiveConnection] = useState<ProgramConnection | null>(null);

  useEffect(() => {
    let connection: ProgramConnection | undefined;
    let closed = false;
    let fallbackStarted = false;
    let directConfirmed = false;
    if (!playbackEnabled) { setState('disabled'); return undefined; }
    const authorizationCleared = () => {
      closed = true;
      connection?.close(); connection = undefined;
      setState('offline');
    };
    window.addEventListener('webobs:browser-authorization-cleared', authorizationCleared);
    const startGateway = async (reason: string) => {
      if (closed || fallbackStarted) return;
      fallbackStarted = true;
      connection?.close(); connection = undefined;
      setTransport('gateway'); setState('connecting');
      try {
        const fallbackPlan = await requestBrowserPlan(source.cameraId, source.profileId, 'unreachable', 'rtsp');
        setPlan(fallbackPlan);
        const gateway = await activateGateway(fallbackPlan.planId);
        if (!closed && videoRef.current) {
          connection = connectApprovedWhep(videoRef.current, gateway.endpoint, setState, {
          deviceToken: gateway.deviceToken, onRemoteStream: (stream) => mixer?.bindStream(source.id, stream),
          onAuthorizationRejected: clearPrivateRuntimeState,
          });
          setActiveConnection(connection);
        }
      } catch (error) {
        if (error instanceof BrowserPlanError && error.kind === 'authorization') {
          authorizationCleared();
          return;
        }
        setPlan({
          contractVersion: 2, planId: '', cameraId: source.cameraId, profileId: source.profileId,
          topology: 'gateway-direct', runtimeKind: 'pwa', executionOwner: 'docker', mediaTransport: 'rtsp',
          credentialExposure: 'none', decoder: 'browser', renderer: 'browser', encoder: 'none',
          liveServerMediaExpected: true, fallbackReason: reason, offlineConfigExpiresAt: 0,
        });
        if (!closed) setState('offline');
      }
    };
    void browserGrantProfile(source.cameraId, source.profileId).then(async (grantedProfile) => {
      const profile = await approvedBrowserProfile(source.cameraId, source.profileId);
      if (closed || !profile?.endpoint) {
        void startGateway(grantedProfile?.browserDirectReason ?? 'browser_profile_not_authorized');
        return;
      }
      setTransport(profile.adapter as 'whep' | 'hls' | 'mjpeg');
      const onState = (next: ProgramConnectionState) => {
        if (closed) return;
        setState(next);
        if (next === 'live' && !directConfirmed) {
          directConfirmed = true;
          void requestBrowserPlan(source.cameraId, source.profileId, 'reachable', profile.adapter)
            .then((value) => setPlan(value)).catch((reason: unknown) => {
              if (reason instanceof BrowserPlanError && reason.kind === 'unavailable')
                void offlineSignedGrantPlan(source.cameraId, source.profileId, profile.adapter as 'whep' | 'hls' | 'mjpeg')
                  .then(setPlan).catch(authorizationCleared);
              else authorizationCleared();
            });
        }
        if (next === 'offline') void startGateway('direct_first_frame_timeout');
      };
      if (profile.adapter === 'whep' && videoRef.current) {
        connection = connectApprovedWhep(videoRef.current, profile.endpoint, onState, {
          onRemoteStream: (stream) => mixer?.bindStream(source.id, stream),
        });
        setActiveConnection(connection);
      } else if (profile.adapter === 'hls' && videoRef.current) {
        connection = connectHls(videoRef.current, profile.endpoint, onState);
        setActiveConnection(connection);
      } else if (profile.adapter === 'mjpeg' && imageRef.current) {
        connection = connectMjpeg(imageRef.current, profile.endpoint, onState);
        setActiveConnection(connection);
      } else void startGateway('protocol_not_supported');
    }).catch(() => startGateway('browser_identity_unavailable'));
    return () => {
      closed = true;
      window.removeEventListener('webobs:browser-authorization-cleared', authorizationCleared);
      connection?.close();
    };
  }, [mixer, playbackEnabled, source.cameraId, source.id, source.profileId]);

  useEffect(() => {
    if (!mixer || !videoRef.current || transport === 'mjpeg') return undefined;
    return mixer.attach(source.id, videoRef.current);
  }, [mixer, source.id, transport]);

  const geometry = useMemo(() => videoGeometry(item, dimensions.width, dimensions.height), [item, dimensions]);
  const trueDirect = plan?.topology === 'true-direct';
  return <div className={`direct-tile ${state}`} data-source-id={source.id}>
    <video ref={videoRef} autoPlay muted playsInline style={{ ...geometry, display: transport === 'mjpeg' ? 'none' : undefined }}
      aria-label={`${source.name} 浏览器媒体画面`} onLoadedMetadata={(event) => setDimensions({ width: event.currentTarget.videoWidth, height: event.currentTarget.videoHeight })} />
    <img ref={imageRef} alt={`${source.name} MJPEG 画面`} style={{ ...geometry, display: transport === 'mjpeg' ? undefined : 'none' }} />
    <span className="direct-tile-state"><i aria-hidden="true" />{labels[state]}</span>
    <div className={`delivery-diagnostic cost-${trueDirect ? 'low' : 'medium'}`}>
      <strong>{trueDirect ? 'TRUE DIRECT' : 'GATEWAY / HYBRID'}</strong>
      <span>媒体：{trueDirect ? 'Camera → Browser' : 'Camera → Docker → Browser'}</span>
      <span>Protocol: {transport.toUpperCase()} · Owner: {plan?.executionOwner ?? 'checking'}</span>
      <span>Decoder: {plan?.decoder ?? 'checking'} · Renderer: {plan?.renderer ?? 'browser'} · Encoder: {plan?.encoder ?? 'checking'}</span>
      <span>Server media: {plan?.liveServerMediaExpected ? 'EXPECTED' : 'OFF'}</span>
      {plan?.fallbackReason && <span>Reason: {plan.fallbackReason}</span>}
    </div>
    {state !== 'live' && <span className="direct-tile-name">{source.name}</span>}
    {lowPower && !lowPower.targetMet && <span className="low-power-unmet">Low-power target: {lowPower.targetFps} FPS<br />Actual source: {lowPower.actualFps || '—'} FPS<br />Target unmet: no low-frame-rate profile</span>}
    <TelemetryOverlay config={telemetry} transport={transport} video={videoRef.current} connection={activeConnection} />
  </div>;
}

export default function DirectPreview({ scene }: { scene: SceneDocument }) {
  const [capabilities, setCapabilities] = useState<SourcePlaybackCapability[]>([]);
  const [available, setAvailable] = useState(true);
  const [mixer, setMixer] = useState<DirectAudioMixer | null>(null);
  const [audio, setAudio] = useState<DirectAudioSnapshot>({ state: 'disabled', inputCount: 0, level: 0 });
  const [monitorView, setMonitorView] = useState<MonitorView>(defaultMonitorView);
  const [monitorLoaded, setMonitorLoaded] = useState(false);
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [analyticsPolicies, setAnalyticsPolicies] = useState<AnalyticsPolicy[]>([]);
  const [portrait, setPortrait] = useState(() => window.matchMedia('(orientation: portrait)').matches);
  const [pageVisible, setPageVisible] = useState(() => !document.hidden);
  const promotionCooldowns = useRef(new Map<string, number>());
  const rotationBag = useRef<string[]>([]);
  const rotationBagSignature = useRef('');
  const promotionTimers = useRef<number[]>([]);

  useEffect(() => {
    const nextMixer = new DirectAudioMixer(setAudio);
    setMixer(nextMixer);
    return () => nextMixer.destroy();
  }, []);

  useEffect(() => {
    const media = window.matchMedia('(orientation: portrait)');
    const changed = () => setPortrait(media.matches);
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);

  useEffect(() => {
    const changed = () => setPageVisible(!document.hidden);
    document.addEventListener('visibilitychange', changed);
    return () => document.removeEventListener('visibilitychange', changed);
  }, []);

  useEffect(() => { void loadMonitorView().then((stored) => {
    if (stored) setMonitorView(normalizeMonitorView(stored, scene.items.length));
    setMonitorLoaded(true);
  }); }, []);

  useEffect(() => {
    if (!monitorLoaded) return;
    const timer = window.setTimeout(() => void saveMonitorView(normalizeMonitorView(monitorView, scene.items.length)), 250);
    return () => window.clearTimeout(timer);
  }, [monitorLoaded, monitorView, scene.items.length]);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([fetchCameras(controller.signal), fetchAnalyticsPolicies(controller.signal)])
      .then(([cameraResult, policyResult]) => { setCameras(cameraResult.cameras); setAnalyticsPolicies(policyResult.policies); })
      .catch(() => undefined);
    return () => controller.abort();
  }, [scene.revision]);

  useEffect(() => mixer?.configure(scene.sources), [mixer, scene.sources]);

  useEffect(() => {
    const controller = new AbortController();
    fetchPlaybackCapabilities(controller.signal)
      .then((result) => {
        setAvailable(result.modes.direct.enabled);
        setCapabilities(result.sources);
      })
      .catch(() => setAvailable(false));
    return () => controller.abort();
  }, [scene.revision]);

  const bySource = useMemo(
    () => new Map(capabilities.map((capability) => [capability.sourceId, capability])),
    [capabilities],
  );
  const audioEnabled = audio.state === 'running';
  const effectiveScene = useMemo(() => {
    let current = monitorView.mode === 'auto' && portrait && scene.canvas.width > scene.canvas.height
      ? { ...scene, canvas: { ...scene.canvas, width: scene.canvas.height, height: scene.canvas.width } }
      : scene;
    if (monitorView.lowPower.enabled && cameras.length) current = {
      ...current,
      sources: current.sources.map((source) => {
        if (source.kind !== 'camera') return source;
        const camera = cameras.find((candidate) => candidate.id === source.cameraId);
        const selected = selectLowPowerProfile(camera?.profiles ?? [], monitorView.lowPower.targetFps);
        return selected.profile ? { ...source, profileId: selected.profile.id } : source;
      }),
    };
    return applyAutomaticLayout(current, monitorView);
  }, [cameras, monitorView, portrait, scene]);
  const lowPowerBySource = useMemo(() => new Map(effectiveScene.sources.flatMap((source) => {
    if (!monitorView.lowPower.enabled || source.kind !== 'camera') return [];
    const camera = cameras.find((candidate) => candidate.id === source.cameraId);
    const selected = selectLowPowerProfile(camera?.profiles ?? [], monitorView.lowPower.targetFps);
    return [[source.id, { targetFps: monitorView.lowPower.targetFps, actualFps: selected.profile?.fps ?? 0, targetMet: selected.targetMet }] as const];
  })), [cameras, effectiveScene.sources, monitorView.lowPower.enabled, monitorView.lowPower.targetFps]);

  useEffect(() => {
    const promote = (event: Event) => {
      const signal = (event as CustomEvent<DetectionSignal>).detail;
      if (!monitorView.promotion.allowEventPromotion || !validDetectionSignal(signal)) return;
      const source = effectiveScene.sources.find((candidate) => candidate.kind === 'camera' &&
        candidate.cameraId === signal.cameraId && candidate.profileId === signal.profileId);
      if (!source || monitorView.largeCount < 1) return;
      const policy = analyticsPolicies.find((candidate) => candidate.cameraId === signal.cameraId && candidate.profileId === signal.profileId);
      if (!policy?.allowEventPromotion || signal.confidence < Math.max(policy.promotionThreshold, monitorView.promotion.threshold)) return;
      if (monitorView.lowPower.enabled && signal.source !== 'camera' && !policy.forceAnalyticsAlwaysOn) return;
      const now = Date.now(); const key = `${signal.cameraId}/${signal.profileId}`;
      if ((promotionCooldowns.current.get(key) ?? 0) > now) return;
      const previous = monitorView.largeSourceIds;
      setMonitorView((value) => ({ ...value, largeSourceIds: [source.id, ...value.largeSourceIds.filter((id) => id !== source.id)].slice(0, value.largeCount) }));
      const hold = Math.max(policy.promotionHoldSeconds, monitorView.promotion.holdSeconds);
      promotionTimers.current.push(window.setTimeout(() => setMonitorView((value) => ({ ...value, largeSourceIds: previous })), hold * 1000));
      promotionCooldowns.current.set(key, now + (hold + Math.max(policy.promotionCooldownSeconds, monitorView.promotion.cooldownSeconds)) * 1000);
    };
    window.addEventListener('webobs:detection-signal', promote);
    return () => window.removeEventListener('webobs:detection-signal', promote);
  }, [analyticsPolicies, effectiveScene.sources, monitorView.largeCount, monitorView.largeSourceIds,
    monitorView.lowPower.enabled, monitorView.promotion]);

  useEffect(() => {
    if (!monitorView.rotation.enabled || monitorView.mode !== 'auto' || monitorView.largeCount < 1) return undefined;
    const rotate = () => {
      if (document.hidden || !navigator.onLine) return;
      const sourceIds = effectiveScene.items.filter((item) => item.visible).map((item) => item.sourceId);
      const candidates = sourceIds.filter((id) => !monitorView.rotation.pinnedSourceIds.includes(id));
      if (monitorView.rotation.strategy === 'random') {
        const signature = [...candidates].sort().join('\u0000');
        if (rotationBagSignature.current !== signature) {
          rotationBag.current = [];
          rotationBagSignature.current = signature;
        }
      }
      const next = nextRotationWindow(sourceIds, monitorView.largeSourceIds, monitorView.largeCount,
        monitorView.rotation.pinnedSourceIds, monitorView.rotation.strategy, rotationBag.current);
      rotationBag.current = next.bag;
      setMonitorView((value) => ({ ...value, largeSourceIds: next.selection }));
    };
    const timer = window.setInterval(rotate, monitorView.rotation.intervalSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [effectiveScene.items, monitorView.largeCount, monitorView.largeSourceIds, monitorView.mode,
    monitorView.rotation.enabled, monitorView.rotation.intervalSeconds, monitorView.rotation.pinnedSourceIds,
    monitorView.rotation.strategy]);

  useEffect(() => () => promotionTimers.current.forEach((timer) => window.clearTimeout(timer)), []);

  return (
    <div className="direct-preview-shell">
      <div
        className="direct-audio-control"
        data-audio-enabled={audioEnabled ? 'true' : 'false'}
        data-audio-state={audio.state}
        data-audio-inputs={audio.inputCount}
        data-audio-level={audio.level.toFixed(4)}
      >
        <button
          type="button"
          aria-pressed={audioEnabled}
          onClick={() => { if (audioEnabled) void mixer?.disable(); else void mixer?.enable(); }}
        >{audioEnabled ? '关闭声音' : '启用声音'}</button>
        <span>{audio.state === 'blocked'
          ? '浏览器阻止了播放，请再次点击。'
          : `Web Audio 混音 · ${audio.inputCount} 路 · 默认静音，点击后启用`}</span>
      </div>
      <div className="monitor-view-controls" aria-label="监控视图设置">
        <button type="button" onClick={() => setMonitorView((value) => ({ ...value, mode: value.mode === 'auto' ? 'manual' : 'auto' }))}>{monitorView.mode === 'auto' ? '脱离自动模式' : '恢复自动布局'}</button>
        <label><input type="checkbox" checked={monitorView.telemetry.enabled} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, enabled: event.target.checked } }))} />统计叠层</label>
        <details><summary>统计字段</summary><div className="monitor-source-options">{(['fps', 'bitrate', 'codec', 'decoder'] as const).map((field) => <label key={field}><input type="checkbox" checked={monitorView.telemetry.fields.includes(field)} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, fields: event.target.checked ? [...new Set([...value.telemetry.fields, field])] : value.telemetry.fields.filter((item) => item !== field) } }))} />{field}</label>)}</div></details>
        <label>位置<select value={monitorView.telemetry.position} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, position: event.target.value as TelemetryOverlayConfig['position'] } }))}>
          <option value="top-left">左上</option><option value="top-right">右上</option><option value="bottom-left">左下</option><option value="bottom-right">右下</option><option value="custom">自定义</option>
        </select></label>
        {monitorView.telemetry.position === 'custom' && <><label>X<input type="range" min="0" max="1" step="0.01" value={monitorView.telemetry.customX} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, customX: Number(event.target.value) } }))} /></label><label>Y<input type="range" min="0" max="1" step="0.01" value={monitorView.telemetry.customY} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, customY: Number(event.target.value) } }))} /></label></>}
        <label>文字透明度<input aria-label="统计文字透明度" type="range" min="0" max="1" step="0.05" value={monitorView.telemetry.textOpacity} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, textOpacity: Number(event.target.value) } }))} /></label>
        <label><input type="checkbox" checked={monitorView.telemetry.backgroundEnabled} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, backgroundEnabled: event.target.checked } }))} />文字框</label>
        {monitorView.telemetry.backgroundEnabled && <><input aria-label="统计文字框颜色" type="color" value={monitorView.telemetry.backgroundColor} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, backgroundColor: event.target.value } }))} /><label>背景透明度<input aria-label="统计背景透明度" type="range" min="0" max="1" step="0.05" value={monitorView.telemetry.backgroundOpacity} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, backgroundOpacity: Number(event.target.value) } }))} /></label></>}
        <label>大画面<input type="number" min="0" max={Math.min(16, scene.items.length)} value={monitorView.largeCount} onChange={(event) => setMonitorView((value) => normalizeMonitorView({ ...value, largeCount: Number(event.target.value) }, scene.items.length))} /></label>
        <details><summary>选择 M / 固定</summary><div className="monitor-source-options">{scene.items.filter((item) => item.visible).slice(0, 16).map((item) => {
          const source = scene.sources.find((candidate) => candidate.id === item.sourceId); const large = monitorView.largeSourceIds.includes(item.sourceId); const pinned = monitorView.rotation.pinnedSourceIds.includes(item.sourceId);
          return <span key={item.sourceId}><label><input type="checkbox" checked={large} onChange={(event) => setMonitorView((value) => ({ ...value, largeSourceIds: event.target.checked ? [...new Set([...value.largeSourceIds, item.sourceId])] : value.largeSourceIds.filter((id) => id !== item.sourceId) }))} />M {source?.name ?? item.sourceId}</label><label><input type="checkbox" checked={pinned} onChange={(event) => setMonitorView((value) => ({ ...value, rotation: { ...value.rotation, pinnedSourceIds: event.target.checked ? [...new Set([...value.rotation.pinnedSourceIds, item.sourceId])] : value.rotation.pinnedSourceIds.filter((id) => id !== item.sourceId) } }))} />固定</label></span>;
        })}</div></details>
        <label><input type="checkbox" checked={monitorView.rotation.enabled} onChange={(event) => setMonitorView((value) => ({ ...value, rotation: { ...value.rotation, enabled: event.target.checked } }))} />大画面轮换</label>
        <select aria-label="轮换策略" value={monitorView.rotation.strategy} onChange={(event) => setMonitorView((value) => ({ ...value, rotation: { ...value.rotation, strategy: event.target.value as 'sequential' | 'random' } }))}><option value="sequential">顺序</option><option value="random">随机</option></select>
        <label>间隔（秒）<input type="number" min="5" max="86400" value={monitorView.rotation.intervalSeconds} onChange={(event) => setMonitorView((value) => normalizeMonitorView({ ...value, rotation: { ...value.rotation, intervalSeconds: Number(event.target.value) } }, scene.items.length))} /></label>
        <label><input type="checkbox" checked={monitorView.promotion.allowEventPromotion} onChange={(event) => setMonitorView((value) => ({ ...value, promotion: { ...value.promotion, allowEventPromotion: event.target.checked } }))} />允许检测事件提升</label>
        <label>阈值<input type="number" min="0" max="1" step="0.05" value={monitorView.promotion.threshold} onChange={(event) => setMonitorView((value) => normalizeMonitorView({ ...value, promotion: { ...value.promotion, threshold: Number(event.target.value) } }, scene.items.length))} /></label>
        <label><input type="checkbox" checked={monitorView.lowPower.enabled} onChange={(event) => setMonitorView((value) => ({ ...value, lowPower: { ...value.lowPower, enabled: event.target.checked } }))} />低功耗</label>
        <label>目标 FPS<input list="low-power-fps" type="number" min="0.5" max="30" step="0.5" value={monitorView.lowPower.targetFps} onChange={(event) => setMonitorView((value) => normalizeMonitorView({ ...value, lowPower: { ...value.lowPower, targetFps: Number(event.target.value) } }, scene.items.length))} /><datalist id="low-power-fps"><option value="0.5" /><option value="1" /><option value="2" /><option value="5" /></datalist></label>
        {monitorView.lowPower.enabled && monitorView.lowPower.targetFps > 5 && <small className="power-warning">超过 5 FPS，节能效果可能有限。</small>}
      </div>
      <div
        className="direct-preview"
        data-direct-available={available ? 'true' : 'false'}
        style={{ aspectRatio: `${effectiveScene.canvas.width} / ${effectiveScene.canvas.height}`, backgroundColor: effectiveScene.canvas.backgroundColor }}
      >
        {[...effectiveScene.items]
          .filter((item) => item.visible)
          .sort((left, right) => left.zIndex - right.zIndex)
          .map((item) => {
            const source = effectiveScene.sources.find((candidate) => candidate.id === item.sourceId);
            if (!source) return null;
            const style = {
              left: `${(item.x / effectiveScene.canvas.width) * 100}%`,
              top: `${(item.y / effectiveScene.canvas.height) * 100}%`,
              width: `${(item.width / effectiveScene.canvas.width) * 100}%`,
              height: `${(item.height / effectiveScene.canvas.height) * 100}%`,
              zIndex: item.zIndex + 1,
            } as CSSProperties;
            return (
              <div className="direct-tile-position" style={style} key={item.id}>
                {source.kind === 'camera'
                  ? <BrowserCameraTile item={item} source={source} mixer={mixer}
                      telemetry={monitorView.lowPower.enabled
                        ? { ...monitorView.telemetry, refreshIntervalMs: Math.max(5000, monitorView.telemetry.refreshIntervalMs) }
                        : monitorView.telemetry}
                      lowPower={lowPowerBySource.get(source.id)}
                      playbackEnabled={!monitorView.lowPower.enabled || pageVisible} />
                  : <DirectTile item={item} source={source} capability={bySource.get(source.id)} mixer={mixer} />}
              </div>
            );
          })}
        {!available && <div className="direct-preview-unavailable">Direct WebRTC 当前不可用；请检查网关状态或显式启用 Composite。</div>}
      </div>
    </div>
  );
}
