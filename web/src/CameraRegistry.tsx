import { useEffect, useState } from 'react';
import { createCamera, deleteCamera, detectCamera, discoverOnvif, fetchCameras, probeOnvif, syncOnvifCamera } from './api';
import type { CameraAdapter, CameraDetection, CameraRecord } from './types';

export default function CameraRegistry({ onBack }: { onBack: () => void }) {
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [address, setAddress] = useState('');
  const [name, setName] = useState('');
  const [credentialsRef, setCredentialsRef] = useState('');
  const [detection, setDetection] = useState<CameraDetection | null>(null);
  const [discovered, setDiscovered] = useState<Array<{ address: string; host: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const reload = async () => { try { setCameras((await fetchCameras()).cameras); } catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取摄像机'); } };
  useEffect(() => { void reload(); }, []);

  const detect = async () => {
    setBusy(true); setError('');
    try {
      const result = await detectCamera(address.trim());
      setDetection(result);
      if (!name) setName(result.address.split('/').filter(Boolean).at(-1) ?? '新摄像机');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '自动检测失败'); }
    finally { setBusy(false); }
  };
  const add = async () => {
    if (!detection) return;
    setBusy(true); setError('');
    try {
      await createCamera({ name: name.trim(), address: detection.address, adapter: detection.adapter,
        credentialsRef: credentialsRef.trim(), hardwareDecode: 'auto', profiles: detection.profiles,
        capabilities: detection.capabilities ?? { probe: detection.probe, contentType: detection.contentType ?? '' } });
      setAddress(''); setName(''); setCredentialsRef(''); setDetection(null); await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '添加失败'); }
    finally { setBusy(false); }
  };
  const readOnvifProfiles = async () => {
    setBusy(true); setError('');
    try {
      const result = await probeOnvif(address.trim(), credentialsRef.trim());
      setDetection(result);
      if (!name) setName('ONVIF 摄像机');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'ONVIF Profile 读取失败'); }
    finally { setBusy(false); }
  };
  const syncOnvif = async (cameraId: string) => {
    setBusy(true); setError('');
    try { await syncOnvifCamera(cameraId); await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'ONVIF 同步失败'); }
    finally { setBusy(false); }
  };

  return <main className="registry-page">
    <header className="registry-header"><div><span className="eyebrow">Camera Source Adapter</span><h1>设备与码流</h1></div><button className="ghost-button" type="button" onClick={onBack}>返回 Studio</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    <section className="registry-add">
      <div><h2>添加设备</h2><p>输入 IP、主机名或 URL。地址中禁止明文账号密码；凭据通过 Secret 引用绑定。</p></div>
      <label><span>地址</span><input value={address} placeholder="camera.example.invalid 或 rtsp://camera.example.invalid/live" onChange={(event) => { setAddress(event.target.value); setDetection(null); }} /></label>
      <div className="registry-actions"><button className="primary-button" disabled={busy || !address.trim()} type="button" onClick={() => void detect()}>自动检测</button><button className="ghost-button" disabled={busy} type="button" onClick={() => void discoverOnvif().then((result) => setDiscovered(result.devices)).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '发现失败'))}>ONVIF 发现</button></div>
      {detection && <div className="detection-result"><strong>{detection.adapter.toUpperCase()} · {detection.probe}{detection.profileVersion ? ` · Profile ${detection.profileVersion}` : ''}</strong><span>{detection.profiles.length ? `${detection.profiles.length} 个码流 Profile` : '等待设备授权后读取 Profile'}</span><label><span>设备名称</span><input value={name} maxLength={128} onChange={(event) => setName(event.target.value)} /></label><label><span>凭据 Secret 引用（可选）</span><input value={credentialsRef} maxLength={256} placeholder="front-door" onChange={(event) => setCredentialsRef(event.target.value.replace(/[^a-zA-Z0-9._/-]/g, ''))} /></label><small>引用 /run/secrets/webobs-camera-credentials/&lt;名称&gt;.json；数据库不保存密码。</small>{detection.adapter === 'onvif' && <button className="ghost-button" disabled={busy || !address.trim()} type="button" onClick={() => void readOnvifProfiles()}>读取 ONVIF Profile</button>}<button className="primary-button" disabled={!name.trim() || (detection.adapter === 'onvif' && detection.profiles.length === 0)} type="button" onClick={() => void add()}>保存到 Registry</button></div>}
      {discovered.length > 0 && <div className="discovery-list">{discovered.map((device) => <button type="button" key={device.address} onClick={() => { setAddress(device.address); setDetection(null); }}><strong>{device.host}</strong><span>{device.address}</span></button>)}</div>}
    </section>
    <section className="camera-list"><div className="section-title"><h2>Camera Registry</h2><span>{cameras.length} 台</span></div>
      {cameras.length === 0 ? <div className="registry-empty"><h3>尚未添加摄像机</h3><p>使用自动检测，或通过 ONVIF WS-Discovery 查找局域网设备。</p></div> : cameras.map((camera) => <article className="camera-card" key={camera.id}><div><span className="adapter-pill">{camera.adapter}</span><h3>{camera.name}</h3><p>{camera.address}</p></div><dl><div><dt>Profile</dt><dd>{camera.profiles.length}</dd></div><div><dt>硬解</dt><dd>{camera.hardwareDecode}</dd></div><div><dt>健康</dt><dd>{camera.health}</dd></div></dl><div className="profile-list">{camera.profiles.map((profile) => <span key={profile.id}>{profile.role} · {profile.videoCodec || 'unknown'} {profile.width ? `${profile.width}×${profile.height}` : ''}</span>)}</div>{camera.adapter === 'onvif' && <button className="ghost-button" disabled={busy} type="button" onClick={() => void syncOnvif(camera.id)}>同步 ONVIF Profile</button>}<button className="danger-button" type="button" onClick={() => { if (window.confirm(`删除 ${camera.name}？`)) void deleteCamera(camera.id).then(reload); }}>删除</button></article>)}
    </section>
    <footer className="adapter-footer">支持：{(['onvif','rtsp','mjpeg','snapshot','hls','http-flv','whep','srt','rtp','v4l2'] as CameraAdapter[]).join(' · ')}</footer>
  </main>;
}
