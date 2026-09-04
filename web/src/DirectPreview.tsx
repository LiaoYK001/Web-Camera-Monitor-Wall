import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react';
import { closeAnalyticsRuntimeSession, fetchAnalyticsPolicies, fetchCameras, fetchMotionZones, fetchPlaybackCapabilities, renewAnalyticsRuntimeSession, requestAnalyticsRuntimePlan, submitAnalyticsSignals } from './api';
import { activateGateway, approvedBrowserProfile, BrowserPlanError, browserGrantProfile, connectApprovedWhep, connectHls, connectMjpeg, offlineSignedGrantPlan, requestBrowserPlan, type BrowserTopologyPlan } from './browserMedia';
import { DirectAudioMixer, type DirectAudioSnapshot } from './directAudioMixer';
import { clearPrivateRuntimeState, loadMonitorView, saveMonitorView } from './localRuntime';
import { observeTileVisibility, shouldRunPlayback } from './mediaLifecycle';
import { countRenderedFrames, formatTelemetry, sampleConnectionTelemetry, sampleElementTelemetry, unavailableTelemetry, type MediaTelemetry } from './mediaTelemetry';
import { applyAutomaticLayout, defaultMonitorView, evaluatePromotion, mapDetectionBoxToTile, nextRotationWindow, normalizeMonitorView, selectLowPowerProfile, sourceDecoration, validDetectionSignal, type AudioMeterConfig, type DetectionSignal, type MonitorView, type TelemetryOverlayConfig } from './monitorView';
import { BrowserAnalyticsRuntime, type BrowserAnalyticsStatus } from './analyticsRuntime';
import { openIssueCenter, reportLocalIssue, reportMediaIssue, resolveLocalIssue } from './issueRuntime';
import type { AnalyticsPolicy, CameraRecord, CameraSceneSource, MotionZone, SceneDocument, SceneItem, SceneSource, SourcePlaybackCapability } from './types';
import { connectSource, type ProgramConnection, type ProgramConnectionState } from './whep';

const labels: Record<ProgramConnectionState, string> = {
  checking: '检查中',
  connecting: '连接中',
  live: '直达',
  reconnecting: '重连中',
  offline: '离线',
  disabled: '未启用',
};

function signalId(prefix: string): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) return `${prefix}-${randomUuid}`;
  // Secure-context browsers expose randomUUID; this bounded fallback keeps
  // local development and older WebViews fail-closed without using a camera
  // identifier or any other sensitive value in the ID.
  const random = Math.random().toString(36).slice(2, 14);
  return `${prefix}-${Date.now().toString(36)}-${random}`;
}

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

function DirectTile({ item, source, capability, mixer, telemetry, audioMeter, audioSnapshot }: {
  item: SceneItem;
  source: SceneSource;
  capability?: SourcePlaybackCapability;
  mixer: DirectAudioMixer | null;
  telemetry?: TelemetryOverlayConfig;
  audioMeter?: AudioMeterConfig;
  audioSnapshot?: { rmsDbfs: number | null; peakDbfs: number | null };
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const [state, setState] = useState<ProgramConnectionState>(capability ? 'checking' : 'offline');
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [activeConnection, setActiveConnection] = useState<ProgramConnection | null>(null);
  const transport: 'whep' | 'gateway' = capability?.strategy === 'passthrough' ? 'whep' : 'gateway';
  const [audioAlert, setAudioAlert] = useState(false);
  const audioPeak = useRef<number | null>(null);
  const audioAlertRef = useRef(false);
  const audioAboveSince = useRef(0);
  const audioBelowSince = useRef(0);

  useEffect(() => {
    if (source.kind === 'camera' || !videoRef.current || !mixer || !capability?.endpoint || capability.preferred !== 'direct') return undefined;
    const connection = connectSource(videoRef.current, capability.endpoint, setState,
      (stream) => mixer.bindStream(source.id, stream));
    setActiveConnection(connection);
    return () => { connection.close(); setActiveConnection(null); };
  }, [capability, mixer, source.id]);

  useEffect(() => {
    if (source.kind === 'camera' || !mixer || !videoRef.current || !capability?.endpoint || capability.preferred !== 'direct') return undefined;
    return mixer.attach(source.id, videoRef.current);
  }, [capability, mixer, source.id]);

  useEffect(() => { audioPeak.current = audioSnapshot?.peakDbfs ?? null; }, [audioSnapshot?.peakDbfs]);
  useEffect(() => {
    audioAlertRef.current = false; audioPeak.current = audioSnapshot?.peakDbfs ?? null;
    if (!audioMeter?.enabled) { setAudioAlert(false); audioAboveSince.current = 0; audioBelowSince.current = 0; return undefined; }
    const timer = window.setInterval(() => {
      const now = Date.now();
      const peak = audioPeak.current;
      if (peak === null || peak === undefined) { audioAlertRef.current = false; setAudioAlert(false); audioAboveSince.current = 0; audioBelowSince.current = 0; return; }
      const above = peak >= audioMeter.thresholdDbfs;
      if (above) {
        audioBelowSince.current = 0;
        if (!audioAboveSince.current) audioAboveSince.current = now;
        if (!audioAlertRef.current && now - audioAboveSince.current >= 250) {
          audioAlertRef.current = true;
          setAudioAlert(true);
          window.dispatchEvent(new CustomEvent('webobs:audio-threshold', { detail: { sourceId: source.id, peakDbfs: peak, promote: false } }));
        }
      } else {
        audioAboveSince.current = 0;
        if (!audioBelowSince.current) audioBelowSince.current = now;
        if (audioAlertRef.current && now - audioBelowSince.current >= 500) { audioAlertRef.current = false; setAudioAlert(false); }
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [audioMeter?.enabled, audioMeter?.thresholdDbfs, source.id]);

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
        ref={(element) => { videoRef.current = element; setVideoElement(element); }}
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
      {capability && capability.strategy !== 'unknown' && <button
        className={`tile-status-button cost-${capability.serverCost ?? 'low'}`} type="button"
        title={`${capability.deliveryMode ?? 'direct'} · 详情见问题中心`}
        onClick={() => openIssueCenter(source.id)} aria-label={`${source.name} 媒体链详情`}>ⓘ</button>}
      {source.kind === 'browser'
        ? <span className="direct-tile-name">{source.name} · 仅服务端合成</span>
        : state !== 'live' && <span className="direct-tile-name">{source.name}</span>}
      {audioAlert && audioMeter?.alertBorderEnabled && <span className="tile-audio-alert-border" style={{ borderColor: colorWithOpacity(audioMeter.alertBorderColor, audioMeter.alertBorderOpacity), borderWidth: `${audioMeter.alertBorderWidth}px` }} aria-label="音频超过阈值" />}
      {audioMeter && <AudioMeterOverlay config={audioMeter} meter={audioSnapshot} />}
      {telemetry && <TelemetryOverlay config={telemetry} transport={transport} video={videoElement} connection={activeConnection} />}
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
  const renderedFrames = useRef(0);
  useEffect(() => {
    renderedFrames.current = 0;
    if (!config.enabled || transport !== 'hls' || !video) return undefined;
    return countRenderedFrames(video, () => { renderedFrames.current += 1; });
  }, [config.enabled, transport, video]);
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
          : video ? sampleElementTelemetry(video, connection, previous, renderedFrames.current) : { telemetry: unavailableTelemetry() };
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

function AudioMeterOverlay({ config, meter }: { config: AudioMeterConfig; meter?: { rmsDbfs: number | null; peakDbfs: number | null } }) {
  if (!config.enabled) return null;
  const peak = meter?.peakDbfs ?? null;
  const width = peak === null ? 0 : Math.max(0, Math.min(100, ((peak + 120) / 120) * 100));
  return <div className={`tile-audio-meter position-${config.position}`} aria-label={peak === null ? '音频电平不可测' : `音频峰值 ${peak.toFixed(1)} dBFS`}>
    <span className="tile-audio-meter-track"><i style={{ width: `${width}%` }} /></span><small>{peak === null ? '—' : `${peak.toFixed(1)} dBFS`}</small>
  </div>;
}

function BrowserCameraTile({ item, source, mixer, telemetry, audioMeter, audioSnapshot, promotionKinds, lowPower, documentVisible, analyticsPolicy, analyticsZones, showAnalytics }: {
  item: SceneItem;
  source: CameraSceneSource;
  mixer: DirectAudioMixer | null;
  telemetry: TelemetryOverlayConfig;
  audioMeter: AudioMeterConfig;
  audioSnapshot?: { rmsDbfs: number | null; peakDbfs: number | null };
  promotionKinds: { audio: boolean; motion: boolean; person: boolean };
  lowPower?: { targetFps: number; actualFps: number; targetMet: boolean };
  documentVisible: boolean;
  analyticsPolicy?: AnalyticsPolicy;
  analyticsZones?: MotionZone[];
  showAnalytics: MonitorView['analytics'];
}) {
  const tileRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const [state, setState] = useState<ProgramConnectionState>('checking');
  const [transport, setTransport] = useState<'whep' | 'hls' | 'mjpeg' | 'gateway'>('gateway');
  const [plan, setPlan] = useState<BrowserTopologyPlan | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [activeConnection, setActiveConnection] = useState<ProgramConnection | null>(null);
  const [tileIntersecting, setTileIntersecting] = useState(true);
  const [analyticsStatus, setAnalyticsStatus] = useState<BrowserAnalyticsStatus>({ state: 'idle', reason: '', sampleFps: 0, lastSignalAt: 0 });
  const [detectionBoxes, setDetectionBoxes] = useState<Array<{ x: number; y: number; width: number; height: number; confidence?: number }>>([]);
  const [audioAlert, setAudioAlert] = useState(false);
  const audioPeak = useRef<number | null>(null);
  const audioAlertRef = useRef(false);
  const audioAboveSince = useRef(0);
  const audioBelowSince = useRef(0);
  const analyticsSession = useRef<string | null>(null);
  // A per-profile forceAnalyticsAlwaysOn policy is the explicit exception to
  // the monitor-wide low-power suspension.  It must keep the media element
  // alive so the browser runtime can actually sample frames.
  const lowPowerForPlayback = Boolean(lowPower) && !Boolean(analyticsPolicy?.forceAnalyticsAlwaysOn);
  const playbackEnabled = shouldRunPlayback({ lowPowerEnabled: lowPowerForPlayback, documentVisible, tileIntersecting });

  useEffect(() => { audioPeak.current = audioSnapshot?.peakDbfs ?? null; }, [audioSnapshot?.peakDbfs]);
  useEffect(() => {
    audioAlertRef.current = false; audioPeak.current = audioSnapshot?.peakDbfs ?? null;
    if (!audioMeter.enabled) { setAudioAlert(false); audioAboveSince.current = 0; audioBelowSince.current = 0; return undefined; }
    const timer = window.setInterval(() => {
      const now = Date.now();
      const peak = audioPeak.current;
      if (peak === null || peak === undefined) { audioAlertRef.current = false; setAudioAlert(false); audioAboveSince.current = 0; audioBelowSince.current = 0; return; }
      const above = peak >= audioMeter.thresholdDbfs;
      if (above) {
        audioBelowSince.current = 0;
        if (!audioAboveSince.current) audioAboveSince.current = now;
        if (!audioAlertRef.current && now - audioAboveSince.current >= 250) {
          audioAlertRef.current = true;
          setAudioAlert(true);
          window.dispatchEvent(new CustomEvent('webobs:audio-threshold', { detail: { sourceId: source.id, peakDbfs: peak, promote: promotionKinds.audio } }));
        }
      } else {
        audioAboveSince.current = 0;
        if (!audioBelowSince.current) audioBelowSince.current = now;
        if (audioAlertRef.current && now - audioBelowSince.current >= 500) { audioAlertRef.current = false; setAudioAlert(false); }
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [audioMeter.enabled, audioMeter.thresholdDbfs, promotionKinds.audio, source.id]);

  useEffect(() => tileRef.current ? observeTileVisibility(tileRef.current, setTileIntersecting) : undefined, []);

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
          onAuthorizationRejected: () => {
            reportMediaIssue({
              code: 'MEDIA_AUTHORIZATION_REJECTED', scopeId: source.id, component: 'browser-media',
              summary: `${source.name} 媒体授权已拒绝`, explanation: '当前设备或授权包已被拒绝，媒体连接已停止。',
              recommendedActions: ['重新登录或重新配对设备。'], technicalDetails: { reason: 'authorization_rejected' },
            });
            return clearPrivateRuntimeState();
          },
          });
          setActiveConnection(connection);
        }
      } catch (error) {
        if (error instanceof BrowserPlanError && error.kind === 'authorization') {
          reportMediaIssue({
            code: 'MEDIA_AUTHORIZATION_REJECTED', scopeId: source.id, component: 'browser-media',
            summary: `${source.name} 媒体授权已拒绝`, explanation: '当前设备或授权包已被拒绝，媒体连接已停止。',
            recommendedActions: ['重新登录或重新配对设备。'], technicalDetails: { reason: 'authorization_rejected' },
          });
          authorizationCleared();
          return;
        }
        reportMediaIssue({
          code: 'MEDIA_GATEWAY_ACTIVATION_FAILED', scopeId: source.id, component: 'browser-media',
          summary: `${source.name} 服务端媒体链启动失败`, explanation: '浏览器直连不可用，且受控 Gateway/Hybrid 会话未能启动。',
          recommendedActions: ['检查 Gateway 状态和 Profile 配置。', '重新探测来源后再试。'],
          technicalDetails: { reason: 'gateway_activation_failed' },
        });
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

  useEffect(() => {
    if (!videoRef.current || !analyticsPolicy || transport === 'mjpeg' || state !== 'live' ||
      (!analyticsPolicy.motionEnabled && !analyticsPolicy.sceneChangeEnabled && !analyticsPolicy.personEnabled)) {
      const unsupportedMjpeg = transport === 'mjpeg' && Boolean(analyticsPolicy && (analyticsPolicy.motionEnabled || analyticsPolicy.sceneChangeEnabled || analyticsPolicy.personEnabled));
      setAnalyticsStatus({ state: unsupportedMjpeg ? 'unsupported' : 'idle', reason: unsupportedMjpeg ? 'pixel_access_denied' : analyticsPolicy ? 'disabled' : 'policy_unavailable', sampleFps: 0, lastSignalAt: 0 });
      setDetectionBoxes([]);
      return undefined;
    }
    let stopped = false;
    let runtime: BrowserAnalyticsRuntime | undefined;
    let renewalTimer = 0;
    const requestedKinds = [analyticsPolicy.motionEnabled ? 'motion' : '', analyticsPolicy.sceneChangeEnabled ? 'scene-change' : '', analyticsPolicy.personEnabled ? 'person' : '']
      .filter(Boolean) as Array<'motion' | 'scene-change' | 'person'>;
    void requestAnalyticsRuntimePlan(source.cameraId, source.profileId, requestedKinds,
      { webgpu: Boolean((navigator as Navigator & { gpu?: unknown }).gpu), wasm: true })
      .then((value) => {
        if (stopped) { void closeAnalyticsRuntimeSession(value.sessionId, source.cameraId, source.profileId).catch(() => undefined); return; }
        analyticsSession.current = value.sessionId;
        const browserKinds = new Set(value.plans.filter((plan) => plan.execution === 'browser-wasm' || plan.execution === 'browser-webgpu').map((plan) => plan.kind));
        const nativeOnly = value.plans.filter((plan) => requestedKinds.includes(plan.kind) && plan.execution === 'native').map((plan) => plan.kind);
        const effectivePolicy: AnalyticsPolicy = {
          ...analyticsPolicy,
          motionEnabled: analyticsPolicy.motionEnabled && browserKinds.has('motion'),
          sceneChangeEnabled: analyticsPolicy.sceneChangeEnabled && browserKinds.has('scene-change'),
          personEnabled: analyticsPolicy.personEnabled && browserKinds.has('person'),
        };
        if (nativeOnly.length && !effectivePolicy.motionEnabled && !effectivePolicy.sceneChangeEnabled && !effectivePolicy.personEnabled)
          setAnalyticsStatus({ state: 'idle', reason: 'camera_native_event', sampleFps: 0, lastSignalAt: 0 });
        const unsupported = value.plans.find((plan) => requestedKinds.includes(plan.kind) && plan.execution === 'unsupported');
        if (unsupported && !effectivePolicy.motionEnabled && !effectivePolicy.sceneChangeEnabled && !effectivePolicy.personEnabled)
          setAnalyticsStatus({ state: 'unsupported', reason: unsupported.reason || 'runtime_unavailable', sampleFps: 0, lastSignalAt: 0 });
        if (!effectivePolicy.motionEnabled && !effectivePolicy.sceneChangeEnabled && !effectivePolicy.personEnabled) return;
        runtime = new BrowserAnalyticsRuntime({
          video: videoRef.current!, cameraId: source.cameraId, profileId: source.profileId, policy: effectivePolicy,
          zones: (analyticsZones ?? []).filter((zone) => zone.cameraId === source.cameraId)
            .map((zone) => ({ mode: zone.mode, polygon: zone.polygon })),
          visible: () => documentVisible && tileIntersecting,
          lowPower: () => Boolean(lowPower),
          onStatus: (status) => {
            setAnalyticsStatus(status);
            const issue = status.reason === 'pixel_access_denied'
              ? { code: 'ANALYTICS_PIXEL_ACCESS_DENIED', summary: `${source.name} 无法读取浏览器像素`, explanation: '当前媒体为跨源或带凭据来源，浏览器不会把画面上传到服务端代为分析。', actions: ['改用支持 CORS 的 HTTPS WHEP/HLS 来源。', '或关闭该 Profile 的浏览器分析。'] }
              : ['model_integrity_failed', 'model_manifest_invalid', 'model_unavailable'].includes(status.reason)
                ? { code: 'ANALYTICS_MODEL_INTEGRITY_FAILED', summary: `${source.name} 人物模型校验失败`, explanation: '固定模型资源未通过清单或 SHA-256 校验，人物分析已停止。', actions: ['重新加载同源模型资源。', '检查镜像版本和公开模型清单。'] }
                : status.reason === 'low_power'
                  ? { code: 'ANALYTICS_LOW_POWER_SUSPENDED', summary: `${source.name} 分析受低功耗策略抑制`, explanation: '低功耗模式已暂停浏览器软件分析；逐流强制开启时才会继续。', actions: ['关闭低功耗模式或降低分析路数。'] }
                  : status.state === 'unsupported' || status.state === 'error'
                    ? { code: 'ANALYTICS_RUNTIME_UNAVAILABLE', summary: `${source.name} 分析运行时不可用`, explanation: '浏览器分析 Worker 或推理运行时不可用，系统未静默启动服务端分析。', actions: ['检查浏览器 Worker/WebAssembly 支持。', '如需服务端 Worker，请由管理员逐流明确启用。'] }
                    : undefined;
            const codes = ['ANALYTICS_PIXEL_ACCESS_DENIED', 'ANALYTICS_MODEL_INTEGRITY_FAILED', 'ANALYTICS_LOW_POWER_SUSPENDED', 'ANALYTICS_RUNTIME_UNAVAILABLE'];
            for (const code of codes) if (!issue || code !== issue.code) resolveLocalIssue(code, source.id, 'browser-analytics');
            if (issue && status.state !== 'running') reportLocalIssue({
              code: issue.code, scopeKind: 'source', scopeId: source.id, component: 'browser-analytics',
              summary: issue.summary, explanation: issue.explanation, recommendedActions: issue.actions,
              technicalDetails: { reason: status.reason }, severity: issue.code === 'ANALYTICS_MODEL_INTEGRITY_FAILED' ? 'error' : 'warning',
            });
          },
          onPersonBoxes: (boxes, execution, model) => {
            setDetectionBoxes(boxes);
            if (boxes.length === 0) {
              if (showAnalytics.showInferenceStatus) setAnalyticsStatus((current) => ({ ...current, state: 'running', reason: execution }));
              return;
            }
            const confidence = boxes.reduce((best, box) => Math.max(best, box.confidence ?? 0), 0);
            const signal: DetectionSignal = { schemaVersion: 2, cameraId: source.cameraId, profileId: source.profileId,
              kind: 'person', occurredAt: Date.now(), confidence, boxes, source: 'browser',
              signalId: signalId('person'), modelId: model.id, modelVersion: model.version, modelSha256: model.sha256 };
            window.dispatchEvent(new CustomEvent('webobs:detection-signal', { detail: signal }));
            if (analyticsSession.current) void submitAnalyticsSignals(analyticsSession.current, [{ cameraId: signal.cameraId, profileId: signal.profileId,
              signalId: signal.signalId, kind: signal.kind, occurredAt: signal.occurredAt, confidence: signal.confidence,
              boxes: signal.boxes, modelId: signal.modelId, modelVersion: signal.modelVersion, modelSha256: signal.modelSha256 }]).catch(() => undefined);
            if (showAnalytics.showInferenceStatus) setAnalyticsStatus((current) => ({ ...current, state: 'running', reason: execution }));
          },
          onSignal: (signal) => {
            if (signal.kind === 'person' && signal.boxes) setDetectionBoxes(signal.boxes);
            window.dispatchEvent(new CustomEvent('webobs:detection-signal', { detail: signal }));
            if (analyticsSession.current) void submitAnalyticsSignals(analyticsSession.current, [{ cameraId: signal.cameraId, profileId: signal.profileId,
              signalId: signal.signalId ?? signalId('signal'), kind: signal.kind, occurredAt: signal.occurredAt, confidence: signal.confidence,
              boxes: signal.boxes, ...(signal.kind === 'person' ? { modelId: signal.modelId, modelVersion: signal.modelVersion, modelSha256: signal.modelSha256 } : {}) }]).catch(() => undefined);
          },
        });
        runtime.start();
        // Runtime plans are intentionally short-lived. Renew while the tab is
        // actively using the profile, preserving the same authenticated owner
        // and Camera/Profile scope; cleanup still closes the session promptly.
        renewalTimer = window.setInterval(() => {
          const session = analyticsSession.current;
          if (!session || stopped) return;
          void renewAnalyticsRuntimeSession(session, source.cameraId, source.profileId).catch(() => undefined);
        }, 4 * 60 * 1000);
      })
      .catch(() => { if (!stopped) setAnalyticsStatus({ state: 'error', reason: 'runtime_plan_unavailable', sampleFps: 0, lastSignalAt: 0 }); });
    return () => { stopped = true; if (renewalTimer) window.clearInterval(renewalTimer); runtime?.stop(); const session = analyticsSession.current; analyticsSession.current = null; if (session) void closeAnalyticsRuntimeSession(session, source.cameraId, source.profileId).catch(() => undefined); };
  }, [analyticsPolicy, analyticsZones, documentVisible, lowPower, source.cameraId, source.profileId, state, tileIntersecting, transport]);

  const geometry = useMemo(() => videoGeometry(item, dimensions.width, dimensions.height), [item, dimensions]);
  const trueDirect = plan?.topology === 'true-direct';
  useEffect(() => {
    if (plan && !trueDirect) reportMediaIssue({
      code: 'MEDIA_DIRECT_FALLBACK', scopeId: source.id, component: 'browser-media',
      summary: `${source.name} 正在使用服务端媒体链`,
      explanation: '浏览器真直连资格或首帧检查未通过，当前画面经 Docker Gateway/Hybrid 传输。',
      recommendedActions: ['检查 Profile 的 HTTPS、CORS 与浏览器直连资格。', '在设备预览中重新执行媒体探测。'],
      technicalDetails: { topology: plan.topology, reason: plan.fallbackReason ?? 'not_true_direct', transportMode: transport },
    });
    else if (trueDirect) resolveLocalIssue('MEDIA_DIRECT_FALLBACK', source.id, 'browser-media');
  }, [plan, source.id, source.name, transport, trueDirect]);
  useEffect(() => {
    if (state === 'offline' && plan && !trueDirect) reportMediaIssue({
      code: 'MEDIA_FIRST_FRAME_TIMEOUT', scopeId: source.id, component: 'browser-media',
      summary: `${source.name} 未收到首帧`, explanation: '媒体会话在限定时间内未建立可播放画面。',
      recommendedActions: ['检查来源在线状态和网络路径。', '重新探测 Profile 或检查 Gateway 状态。'],
      technicalDetails: { transport },
    });
    else if (state === 'live') resolveLocalIssue('MEDIA_FIRST_FRAME_TIMEOUT', source.id, 'browser-media');
  }, [plan, source.id, source.name, state, transport, trueDirect]);
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('webobs:media-topology', { detail: {
      sourceId: source.id,
      topology: plan?.topology ?? 'checking',
      executionOwner: plan?.executionOwner ?? 'unknown',
      mediaTransport: plan?.mediaTransport ?? transport,
      decoder: plan?.decoder ?? 'unknown',
      liveServerMediaExpected: plan?.liveServerMediaExpected ?? null,
      fallbackReason: plan?.fallbackReason ?? '',
    } }));
  }, [plan, source.id, transport]);
  useEffect(() => {
    const code = 'LOW_POWER_TARGET_UNMET';
    if (lowPower && !lowPower.targetMet) reportLocalIssue({
      code, scopeId: source.id, component: 'low-power', summary: `${source.name} 未达到低功耗帧率目标`,
      explanation: 'Camera Registry 中没有符合目标帧率的低成本 Profile；系统不会为此启动服务端转码。',
      recommendedActions: ['为设备增加低帧率子码流或 Snapshot Profile。'],
      technicalDetails: { reason: 'no_low_frame_rate_profile' },
    });
    else resolveLocalIssue(code, source.id, 'low-power');
  }, [lowPower, source.id, source.name]);
  return <div ref={tileRef} className={`direct-tile ${state}`} data-source-id={source.id}
    data-playback-suspended={playbackEnabled ? 'false' : 'true'}>
    <video ref={(element) => { videoRef.current = element; setVideoElement(element); }} autoPlay muted playsInline style={{ ...geometry, display: transport === 'mjpeg' ? 'none' : undefined }}
      aria-label={`${source.name} 浏览器媒体画面`} onLoadedMetadata={(event) => setDimensions({ width: event.currentTarget.videoWidth, height: event.currentTarget.videoHeight })} />
    <img ref={imageRef} alt={`${source.name} MJPEG 画面`} style={{ ...geometry, display: transport === 'mjpeg' ? undefined : 'none' }} />
    <span className="direct-tile-state"><i aria-hidden="true" />{labels[state]}</span>
    <button className={`tile-status-button ${trueDirect ? 'cost-low' : 'cost-medium'}`} type="button"
      aria-label={`${source.name} 媒体路径详情`} onClick={() => openIssueCenter(source.id)}
      title={trueDirect ? `Camera → Browser · ${transport.toUpperCase()}` : 'Camera → Docker → Browser · 详情见问题中心'}>ⓘ</button>
    {state !== 'live' && <span className="direct-tile-name">{source.name}</span>}
    {audioAlert && audioMeter.alertBorderEnabled && <span className="tile-audio-alert-border" style={{ borderColor: colorWithOpacity(audioMeter.alertBorderColor, audioMeter.alertBorderOpacity), borderWidth: `${audioMeter.alertBorderWidth}px` }} aria-label="音频超过阈值" />}
    {showAnalytics.showDetectionBoxes && detectionBoxes.map((box, index) => {
      const mapped = mapDetectionBoxToTile(box, item, dimensions.width, dimensions.height);
      if (mapped.width <= 0 || mapped.height <= 0) return null;
      return <span key={`${source.id}-box-${index}`} className="detection-box" style={{
        left: `${mapped.x * 100}%`, top: `${mapped.y * 100}%`, width: `${mapped.width * 100}%`, height: `${mapped.height * 100}%`,
        opacity: showAnalytics.boxOpacity, borderWidth: `${showAnalytics.boxLineWidth}px`,
      }} aria-hidden="true">{showAnalytics.showDetectionLabels && <small>person</small>}</span>;
    })}
    <AudioMeterOverlay config={audioMeter} meter={audioSnapshot} />
    <TelemetryOverlay config={telemetry} transport={transport} video={videoElement} connection={activeConnection} />
  </div>;
}

export default function DirectPreview({ scene, compact = false }: { scene: SceneDocument; compact?: boolean }) {
  const [capabilities, setCapabilities] = useState<SourcePlaybackCapability[]>([]);
  const [available, setAvailable] = useState(true);
  const [mixer, setMixer] = useState<DirectAudioMixer | null>(null);
  const [audio, setAudio] = useState<DirectAudioSnapshot>({ state: 'disabled', inputCount: 0, level: 0, sources: [] });
  const [monitorView, setMonitorView] = useState<MonitorView>(defaultMonitorView);
  const [monitorLoaded, setMonitorLoaded] = useState(false);
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [analyticsPolicies, setAnalyticsPolicies] = useState<AnalyticsPolicy[]>([]);
  const [analyticsZones, setAnalyticsZones] = useState<MotionZone[]>([]);
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
    const enable = () => void mixer?.enable();
    const disable = () => void mixer?.disable();
    window.addEventListener('webobs:audio-monitor-enable', enable);
    window.addEventListener('webobs:audio-monitor-disable', disable);
    return () => {
      window.removeEventListener('webobs:audio-monitor-enable', enable);
      window.removeEventListener('webobs:audio-monitor-disable', disable);
    };
  }, [mixer]);

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
    if (stored) setMonitorView(normalizeMonitorView(stored, scene.items.length, scene.sources.map((source) => source.id)));
    setMonitorLoaded(true);
  }); }, []);

  useEffect(() => {
    if (!monitorLoaded) return;
    const timer = window.setTimeout(() => void saveMonitorView(normalizeMonitorView(monitorView, scene.items.length, scene.sources.map((source) => source.id))), 250);
    return () => window.clearTimeout(timer);
  }, [monitorLoaded, monitorView, scene.items.length]);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([fetchCameras(controller.signal), fetchAnalyticsPolicies(controller.signal), fetchMotionZones(controller.signal)])
      .then(([cameraResult, policyResult, zoneResult]) => { setCameras(cameraResult.cameras); setAnalyticsPolicies(policyResult.policies); setAnalyticsZones(zoneResult.zones); })
      .catch(() => undefined);
    return () => controller.abort();
  }, [scene.revision]);

  useEffect(() => mixer?.configure(scene.sources), [mixer, scene.sources]);
  useEffect(() => mixer?.setMasterVolume(monitorView.localMonitorVolume), [mixer, monitorView.localMonitorVolume]);

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
  const audioBySource = useMemo(() => new Map(audio.sources.map((value) => [value.sourceId, value])), [audio.sources]);
  useEffect(() => {
    if (audio.state === 'blocked') reportMediaIssue({
      code: 'AUDIO_RUNTIME_UNAVAILABLE', scopeId: 'monitor', component: 'direct-audio',
      summary: '浏览器音频运行时不可用', explanation: '浏览器未允许启动本地音频分析或监听，画面仍保持静音。',
      recommendedActions: ['通过用户手势启用监听。', '检查浏览器音频权限和输出设备。'],
      technicalDetails: { reason: 'audio_context_blocked' },
    });
    else if (audio.state === 'running') resolveLocalIssue('AUDIO_RUNTIME_UNAVAILABLE', 'monitor', 'direct-audio');
  }, [audio.state]);
  const analyticsByProfile = useMemo(() => new Map(analyticsPolicies.map((policy) => [`${policy.cameraId}\u0000${policy.profileId}`, policy])), [analyticsPolicies]);
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

  const updateSourceDecoration = (sourceId: string, change: Partial<ReturnType<typeof sourceDecoration>>) => {
    setMonitorView((value) => {
      const current = sourceDecoration(value, sourceId);
      return normalizeMonitorView({ ...value, sourceDecorations: {
        ...value.sourceDecorations,
        [sourceId]: { ...current, ...change, telemetry: { ...current.telemetry, ...(change.telemetry ?? {}) }, audioMeter: { ...current.audioMeter, ...(change.audioMeter ?? {}) }, promotionKinds: { ...current.promotionKinds, ...(change.promotionKinds ?? {}) } },
      } }, scene.items.length);
    });
  };

  useEffect(() => {
    const promote = (event: Event) => {
      const signal = (event as CustomEvent<DetectionSignal>).detail;
      if (!validDetectionSignal(signal)) return;
      const source = effectiveScene.sources.find((candidate) => candidate.kind === 'camera' &&
        candidate.cameraId === signal.cameraId && candidate.profileId === signal.profileId);
      if (!source || monitorView.largeCount < 1) return;
      const policy = analyticsPolicies.find((candidate) => candidate.cameraId === signal.cameraId && candidate.profileId === signal.profileId);
      const now = Date.now(); const key = `${signal.cameraId}/${signal.profileId}`;
      const decision = evaluatePromotion(signal, policy, {
        enabled: monitorView.promotion.allowEventPromotion, threshold: monitorView.promotion.threshold,
        holdSeconds: monitorView.promotion.holdSeconds, cooldownSeconds: monitorView.promotion.cooldownSeconds,
        lowPowerEnabled: monitorView.lowPower.enabled, now,
        cooldownUntil: promotionCooldowns.current.get(key) ?? 0,
      });
      if (!decision.accepted) return;
      const previous = monitorView.largeSourceIds;
      setMonitorView((value) => ({ ...value, largeSourceIds: [source.id, ...value.largeSourceIds.filter((id) => id !== source.id)].slice(0, value.largeCount) }));
      const hold = Math.max(1, (decision.holdUntil - now) / 1000);
      promotionTimers.current.push(window.setTimeout(() => setMonitorView((value) => ({ ...value, largeSourceIds: previous })), hold * 1000));
      promotionCooldowns.current.set(key, decision.cooldownUntil);
    };
    window.addEventListener('webobs:detection-signal', promote);
    return () => window.removeEventListener('webobs:detection-signal', promote);
  }, [analyticsPolicies, effectiveScene.sources, monitorView.largeCount, monitorView.largeSourceIds,
    monitorView.lowPower.enabled, monitorView.promotion]);

  useEffect(() => {
    const promoteAudio = (event: Event) => {
      const detail = (event as CustomEvent<{ sourceId?: string; peakDbfs?: number; promote?: boolean }>).detail;
      if (!detail?.sourceId || !detail.promote || !Number.isFinite(detail.peakDbfs) || monitorView.largeCount < 1) return;
      const source = effectiveScene.sources.find((candidate) => candidate.id === detail.sourceId);
      if (!source || !sourceDecoration(monitorView, source.id).promotionKinds.audio || monitorView.lowPower.enabled) return;
      const now = Date.now(); const key = `audio/${source.id}`; const cooldownUntil = promotionCooldowns.current.get(key) ?? 0;
      if (cooldownUntil > now || !monitorView.promotion.allowEventPromotion) return;
      const decoration = sourceDecoration(monitorView, source.id);
      if ((detail.peakDbfs ?? -120) < decoration.audioMeter.thresholdDbfs) return;
      const previous = monitorView.largeSourceIds;
      setMonitorView((value) => ({ ...value, largeSourceIds: [source.id, ...value.largeSourceIds.filter((id) => id !== source.id)].slice(0, value.largeCount) }));
      const holdMs = Math.max(1, monitorView.promotion.holdSeconds) * 1000;
      promotionTimers.current.push(window.setTimeout(() => setMonitorView((value) => ({ ...value, largeSourceIds: previous })), holdMs));
      promotionCooldowns.current.set(key, now + holdMs + Math.max(0, monitorView.promotion.cooldownSeconds) * 1000);
    };
    window.addEventListener('webobs:audio-threshold', promoteAudio);
    return () => window.removeEventListener('webobs:audio-threshold', promoteAudio);
  }, [effectiveScene.sources, monitorView, monitorView.largeCount, monitorView.lowPower.enabled]);

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
      {!compact && <><div
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
        <label>本地音量 <input aria-label="本地监听主音量" type="range" min="0" max="1" step="0.01"
          value={monitorView.localMonitorVolume} onChange={(event) => setMonitorView((value) => ({ ...value, localMonitorVolume: Number(event.target.value) }))} /></label>
        <span>{audio.state === 'blocked'
          ? '浏览器阻止了播放，请再次点击。'
          : `Web Audio 混音 · ${audio.inputCount} 路 · 默认静音，点击后启用`}</span>
      </div>
      <div className="monitor-view-controls" aria-label="监控视图设置">
        <button type="button" onClick={() => setMonitorView((value) => ({ ...value, mode: value.mode === 'auto' ? 'manual' : 'auto' }))}>{monitorView.mode === 'auto' ? '脱离自动模式' : '恢复自动布局'}</button>
        <label><input type="checkbox" checked={monitorView.telemetry.enabled} onChange={(event) => setMonitorView((value) => ({ ...value, telemetry: { ...value.telemetry, enabled: event.target.checked } }))} />统计叠层（默认）</label>
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
        <details><summary>逐路统计 / 音频告警</summary><div className="monitor-source-options monitor-decoration-options">{effectiveScene.sources.filter((source) => source.kind === 'camera').slice(0, 16).map((source) => {
          const decoration = sourceDecoration(monitorView, source.id);
          return <fieldset key={source.id}><legend>{source.name}</legend>
            <label><input type="checkbox" checked={decoration.telemetry.enabled} onChange={(event) => updateSourceDecoration(source.id, { telemetry: { ...decoration.telemetry, enabled: event.target.checked } })} />统计</label>
            {(['fps', 'bitrate', 'codec', 'decoder'] as const).map((field) => <label key={field}><input type="checkbox" checked={decoration.telemetry.fields.includes(field)} onChange={(event) => updateSourceDecoration(source.id, { telemetry: { ...decoration.telemetry, fields: event.target.checked ? [...new Set([...decoration.telemetry.fields, field])] : decoration.telemetry.fields.filter((item) => item !== field) } })} />{field}</label>)}
            <label><input type="checkbox" checked={decoration.audioMeter.enabled} onChange={(event) => updateSourceDecoration(source.id, { audioMeter: { ...decoration.audioMeter, enabled: event.target.checked } })} />画面音频表</label>
            <label>阈值 <input type="number" min="-120" max="0" step="1" value={decoration.audioMeter.thresholdDbfs} onChange={(event) => updateSourceDecoration(source.id, { audioMeter: { ...decoration.audioMeter, thresholdDbfs: Number(event.target.value) } })} /> dBFS</label>
            <label><input type="checkbox" checked={decoration.audioMeter.alertBorderEnabled} onChange={(event) => updateSourceDecoration(source.id, { audioMeter: { ...decoration.audioMeter, alertBorderEnabled: event.target.checked } })} />超阈值边框</label>
            <label><input type="checkbox" checked={decoration.promotionKinds.audio} onChange={(event) => updateSourceDecoration(source.id, { promotionKinds: { ...decoration.promotionKinds, audio: event.target.checked } })} />音频提升 M</label>
            <label><input type="checkbox" checked={decoration.promotionKinds.motion} onChange={(event) => updateSourceDecoration(source.id, { promotionKinds: { ...decoration.promotionKinds, motion: event.target.checked } })} />Motion 提升（预留）</label>
            <label><input type="checkbox" checked={decoration.promotionKinds.person} onChange={(event) => updateSourceDecoration(source.id, { promotionKinds: { ...decoration.promotionKinds, person: event.target.checked } })} />Person 提升（预留）</label>
          </fieldset>;
        })}</div></details>
      </div></>}
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
              opacity: item.opacity,
              transform: `rotate(${item.rotation}deg)`,
            } as CSSProperties;
            return (
              <div className="direct-tile-position" style={style} key={item.id}>
                {source.kind === 'camera'
                  ? <BrowserCameraTile item={item} source={source} mixer={mixer}
                      telemetry={monitorView.lowPower.enabled
                        ? { ...sourceDecoration(monitorView, source.id).telemetry, refreshIntervalMs: Math.max(5000, sourceDecoration(monitorView, source.id).telemetry.refreshIntervalMs) }
                        : sourceDecoration(monitorView, source.id).telemetry}
                      audioMeter={sourceDecoration(monitorView, source.id).audioMeter}
                      audioSnapshot={audioBySource.get(source.id)}
                      promotionKinds={sourceDecoration(monitorView, source.id).promotionKinds}
                      lowPower={lowPowerBySource.get(source.id)}
                      documentVisible={pageVisible}
                      analyticsPolicy={analyticsByProfile.get(`${source.cameraId}\u0000${source.profileId}`)}
                      analyticsZones={analyticsZones}
                      showAnalytics={monitorView.analytics} />
                  : <DirectTile item={item} source={source} capability={bySource.get(source.id)} mixer={mixer}
                      telemetry={monitorView.lowPower.enabled
                        ? { ...sourceDecoration(monitorView, source.id).telemetry, refreshIntervalMs: Math.max(5000, sourceDecoration(monitorView, source.id).telemetry.refreshIntervalMs) }
                        : sourceDecoration(monitorView, source.id).telemetry}
                      audioMeter={sourceDecoration(monitorView, source.id).audioMeter} audioSnapshot={audioBySource.get(source.id)} />}
              </div>
            );
          })}
      </div>
    </div>
  );
}
