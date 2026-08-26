import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react';
import { fetchPlaybackCapabilities } from './api';
import { activateGateway, approvedBrowserProfile, BrowserPlanError, browserGrantProfile, connectApprovedWhep, connectHls, connectMjpeg, offlineSignedGrantPlan, requestBrowserPlan, type BrowserTopologyPlan } from './browserMedia';
import { DirectAudioMixer, type DirectAudioSnapshot } from './directAudioMixer';
import { clearPrivateRuntimeState } from './localRuntime';
import type { CameraSceneSource, SceneDocument, SceneItem, SceneSource, SourcePlaybackCapability } from './types';
import { connectSource, type ProgramConnectionState } from './whep';

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

  if (source.kind === 'camera') return <BrowserCameraTile item={item} source={source} mixer={mixer} />;

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

function BrowserCameraTile({ item, source, mixer }: {
  item: SceneItem;
  source: CameraSceneSource;
  mixer: DirectAudioMixer | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [state, setState] = useState<ProgramConnectionState>('checking');
  const [transport, setTransport] = useState<'whep' | 'hls' | 'mjpeg' | 'gateway'>('gateway');
  const [plan, setPlan] = useState<BrowserTopologyPlan | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    let connection: { close: () => void } | undefined;
    let closed = false;
    let fallbackStarted = false;
    let directConfirmed = false;
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
        if (!closed && videoRef.current) connection = connectApprovedWhep(videoRef.current, gateway.endpoint, setState, {
          deviceToken: gateway.deviceToken, onRemoteStream: (stream) => mixer?.bindStream(source.id, stream),
          onAuthorizationRejected: clearPrivateRuntimeState,
        });
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
      if (profile.adapter === 'whep' && videoRef.current)
        connection = connectApprovedWhep(videoRef.current, profile.endpoint, onState, {
          onRemoteStream: (stream) => mixer?.bindStream(source.id, stream),
        });
      else if (profile.adapter === 'hls' && videoRef.current)
        connection = connectHls(videoRef.current, profile.endpoint, onState);
      else if (profile.adapter === 'mjpeg' && imageRef.current)
        connection = connectMjpeg(imageRef.current, profile.endpoint, onState);
      else void startGateway('protocol_not_supported');
    }).catch(() => startGateway('browser_identity_unavailable'));
    return () => {
      closed = true;
      window.removeEventListener('webobs:browser-authorization-cleared', authorizationCleared);
      connection?.close();
    };
  }, [mixer, source.cameraId, source.id, source.profileId]);

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
  </div>;
}

export default function DirectPreview({ scene }: { scene: SceneDocument }) {
  const [capabilities, setCapabilities] = useState<SourcePlaybackCapability[]>([]);
  const [available, setAvailable] = useState(true);
  const [mixer, setMixer] = useState<DirectAudioMixer | null>(null);
  const [audio, setAudio] = useState<DirectAudioSnapshot>({ state: 'disabled', inputCount: 0, level: 0 });

  useEffect(() => {
    const nextMixer = new DirectAudioMixer(setAudio);
    setMixer(nextMixer);
    return () => nextMixer.destroy();
  }, []);

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
      <div
        className="direct-preview"
        data-direct-available={available ? 'true' : 'false'}
        style={{ aspectRatio: `${scene.canvas.width} / ${scene.canvas.height}`, backgroundColor: scene.canvas.backgroundColor }}
      >
        {[...scene.items]
          .filter((item) => item.visible)
          .sort((left, right) => left.zIndex - right.zIndex)
          .map((item) => {
            const source = scene.sources.find((candidate) => candidate.id === item.sourceId);
            if (!source) return null;
            const style = {
              left: `${(item.x / scene.canvas.width) * 100}%`,
              top: `${(item.y / scene.canvas.height) * 100}%`,
              width: `${(item.width / scene.canvas.width) * 100}%`,
              height: `${(item.height / scene.canvas.height) * 100}%`,
              zIndex: item.zIndex + 1,
            } as CSSProperties;
            return (
              <div className="direct-tile-position" style={style} key={item.id}>
                <DirectTile
                  item={item}
                  source={source}
                  capability={bySource.get(source.id)}
                  mixer={mixer}
                />
              </div>
            );
          })}
        {!available && <div className="direct-preview-unavailable">Direct WebRTC 当前不可用；请检查网关状态或显式启用 Composite。</div>}
      </div>
    </div>
  );
}
