import { useEffect, useState } from 'react';
import { acknowledgeEvent, createEvent, createEventRule, createMotionZone, fetchCameras, fetchEventRules, fetchEvents, fetchMotionZones } from './api';
import type { CameraRecord, EventRule, MonitorEvent, MotionZone } from './types';

export default function EventsPanel({ onBack }: { onBack: () => void }) {
  const [events, setEvents] = useState<MonitorEvent[]>([]); const [zones, setZones] = useState<MotionZone[]>([]);
  const [rules, setRules] = useState<EventRule[]>([]); const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [cameraId, setCameraId] = useState(''); const [type, setType] = useState(''); const [error, setError] = useState('');
  const reload = async () => {
    const query = new URLSearchParams(); if (cameraId) query.set('cameraId', cameraId); if (type) query.set('type', type);
    try { const [eventResult, zoneResult, ruleResult, cameraResult] = await Promise.all([fetchEvents(query.toString()), fetchMotionZones(), fetchEventRules(), fetchCameras()]); setEvents(eventResult.events); setZones(zoneResult.zones); setRules(ruleResult.rules); setCameras(cameraResult.cameras); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取事件'); }
  };
  useEffect(() => { void reload(); }, [cameraId, type]);
  const selectedCamera = cameraId || cameras[0]?.id || '';
  return <main className="events-page">
    <header className="registry-header"><div><span className="eyebrow">Events & Automation</span><h1>事件中心</h1></div><button className="ghost-button" onClick={onBack}>返回 Studio</button></header>
    {error && <div className="alert" role="alert">{error}</div>}
    <section className="events-toolbar"><select value={cameraId} onChange={(event) => setCameraId(event.target.value)}><option value="">全部摄像机</option>{cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.name}</option>)}</select><select value={type} onChange={(event) => setType(event.target.value)}><option value="">全部类型</option>{['motion','tamper','line-crossing','region-crossing','object','sound','device-health','recording-failure','manual-marker'].map((value) => <option key={value}>{value}</option>)}</select><button disabled={!selectedCamera} onClick={() => void createEvent({ cameraId: selectedCamera, type: 'manual-marker', source: 'manual', properties: {} }).then(reload).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '标记失败'))}>添加人工标记</button></section>
    <section className="event-grid"><div className="event-list"><h2>事件记录 <small>{events.length}</small></h2>{events.length === 0 ? <p className="registry-empty">当前筛选条件下没有事件</p> : events.map((event) => <article key={event.id} className={`event-card ${event.severity}`}><header><strong>{event.type}{event.label ? ` · ${event.label}` : ''}</strong><time>{new Date(event.occurredAt).toLocaleString()}</time></header><p>{event.cameraId} · {event.source}{event.zoneId ? ` · ${event.zoneId}` : ''}</p><small>{event.segmentIds.length ? `已关联 ${event.segmentIds.length} 个录像分段` : '暂无关联录像'}</small><button className="ghost-button" onClick={() => void acknowledgeEvent(event.id, !event.acknowledged, event.acknowledged ? '' : 'WebUI acknowledged').then(reload)}>{event.acknowledged ? '重新打开' : '确认'}</button></article>)}</div>
      <aside className="automation-panel"><h2>检测与自动化</h2><p>移动区 {zones.length} · 规则 {rules.length}</p><button disabled={!selectedCamera} onClick={() => void createMotionZone({ cameraId: selectedCamera, name: `全画面 ${zones.length + 1}`, mode: 'include', polygon: [[0,0],[1,0],[1,1],[0,1]], sensitivity: .15, debounceMs: 500, cooldownMs: 5000, enabled: true }).then(reload)}>新增全画面移动区</button><button disabled={!selectedCamera} onClick={() => void createEventRule({ name: `移动事件规则 ${rules.length + 1}`, enabled: true, conditions: { cameraId: selectedCamera, type: 'motion' }, actions: [], cooldownMs: 5000 }).then(reload)}>新增移动规则</button><small>Webhook/MQTT 目标仅通过挂载的 Secret 引用配置；UI 和数据库均不保存通知凭据。</small></aside>
    </section>
  </main>;
}
