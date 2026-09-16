import type { CameraProfile, SceneDocument, SceneItem } from './types';

export type TelemetryField = 'fps' | 'bitrate' | 'codec' | 'decoder';
export type OverlayPosition = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'custom';

export interface TelemetryOverlayConfig {
  enabled: boolean;
  fields: TelemetryField[];
  position: OverlayPosition;
  customX: number;
  customY: number;
  textOpacity: number;
  backgroundEnabled: boolean;
  backgroundColor: string;
  backgroundOpacity: number;
  refreshIntervalMs: number;
}

/**
 * How a source is fitted into its Scene tile.  The monitor wall defaults to
 * `stretch` so monitoring corners are never cropped away; `contain` keeps the
 * full frame with possible letterboxing and `cover` crops to fill.
 */
export type VideoFillMode = 'stretch' | 'contain' | 'cover';
export const videoFillModes: VideoFillMode[] = ['stretch', 'contain', 'cover'];

export type AudioMeterOrientation = 'vertical' | 'horizontal';
export type AudioMeterPosition = 'left' | 'right' | OverlayPosition;

export interface AudioMeterConfig {
  enabled: boolean;
  /** OBS-style meter direction; the default is a vertical bar so it never covers tile labels. */
  orientation: AudioMeterOrientation;
  position: AudioMeterPosition;
  /** Scale of the meter's long axis, 0.3 - 2. */
  size: number;
  /** Meter opacity, 0.1 - 1. */
  opacity: number;
  customX: number;
  customY: number;
  thresholdDbfs: number;
  alertBorderEnabled: boolean;
  alertBorderColor: string;
  alertBorderOpacity: number;
  alertBorderWidth: number;
}

export interface SourceDecoration {
  telemetry: TelemetryOverlayConfig;
  audioMeter: AudioMeterConfig;
  promotionKinds: { audio: boolean; motion: boolean; person: boolean };
  /** Per-source fill override; when absent the monitor-level fill applies. */
  fill?: VideoFillMode;
}

export interface RotationConfig {
  enabled: boolean;
  strategy: 'sequential' | 'random';
  intervalSeconds: number;
  pinnedSourceIds: string[];
}

export interface PromotionConfig {
  allowEventPromotion: boolean;
  threshold: number;
  holdSeconds: number;
  cooldownSeconds: number;
}

export interface LowPowerConfig {
  enabled: boolean;
  targetFps: number;
}

export interface MonitorView {
  schemaVersion: 4;
  mode: 'auto' | 'manual';
  largeCount: number;
  largeSourceIds: string[];
  /** Small tile size as a share of the large tile, 0.1 - 0.9. */
  largeRatio: number;
  telemetry: TelemetryOverlayConfig;
  /** Default tile fill for the automatic layout. */
  fill: VideoFillMode;
  sourceDecorations: Record<string, SourceDecoration>;
  rotation: RotationConfig;
  promotion: PromotionConfig;
  lowPower: LowPowerConfig;
  panels: { detailsOpen: boolean; issueCenterExpanded: boolean };
  localMonitorVolume: number;
  /** Speaker routing: full monitoring output or meter/threshold detection only. */
  audioOutput: 'speaker' | 'meter-only';
  analytics: {
    showDetectionBoxes: boolean;
    showDetectionLabels: boolean;
    boxOpacity: number;
    boxLineWidth: number;
    showInferenceStatus: boolean;
  };
}

export interface DetectionSignal {
  schemaVersion: 1 | 2;
  signalId?: string;
  cameraId: string;
  profileId: string;
  kind: 'motion' | 'scene-change' | 'person';
  occurredAt: number;
  confidence: number;
  boxes?: Array<{ x: number; y: number; width: number; height: number }>;
  source: 'camera' | 'browser' | 'server' | 'external';
  modelId?: string;
  modelVersion?: string;
  modelSha256?: string;
}

export interface TileTransform {
  /** Visible content box inside the Scene item, in item units. */
  contentWidth: number;
  contentHeight: number;
  /** CSS element box; equals the content box except for stretch-with-crop. */
  elementWidth: number;
  elementHeight: number;
  /** Element offset inside the Scene item, in item units. */
  offsetX: number;
  offsetY: number;
  /** Source-pixel to Scene-item-unit scale, including crop and fill mode. */
  scaleX: number;
  scaleY: number;
}

/**
 * Single geometry source for the video element, detection boxes, masks and
 * overlays.  The same crop + contain/cover/stretch math is applied everywhere
 * so a box never drifts from the picture it marks.
 */
export function tileTransform(item: SceneItem, sourceWidth: number, sourceHeight: number): TileTransform {
  const cropLeft = Math.max(0, item.crop.left);
  const cropTop = Math.max(0, item.crop.top);
  const croppedWidth = Math.max(1, sourceWidth - cropLeft - Math.max(0, item.crop.right));
  const croppedHeight = Math.max(1, sourceHeight - cropTop - Math.max(0, item.crop.bottom));
  const fitX = item.width / croppedWidth;
  const fitY = item.height / croppedHeight;
  const scale = item.scaleMode === 'contain' ? Math.min(fitX, fitY)
    : item.scaleMode === 'cover' ? Math.max(fitX, fitY) : 0;
  const scaleX = item.scaleMode === 'stretch' ? fitX : scale;
  const scaleY = item.scaleMode === 'stretch' ? fitY : scale;
  const contentWidth = item.scaleMode === 'stretch' ? item.width : croppedWidth * scale;
  const contentHeight = item.scaleMode === 'stretch' ? item.height : croppedHeight * scale;
  return {
    contentWidth,
    contentHeight,
    elementWidth: item.scaleMode === 'stretch' ? sourceWidth * scaleX : contentWidth,
    elementHeight: item.scaleMode === 'stretch' ? sourceHeight * scaleY : contentHeight,
    offsetX: (item.width - contentWidth) / 2 - cropLeft * scaleX,
    offsetY: (item.height - contentHeight) / 2 - cropTop * scaleY,
    scaleX,
    scaleY,
  };
}

/**
 * Map a source-normalized detection box onto a Scene v5 tile.  Values are
 * clamped to the tile; an entirely cropped-out box is returned with zero
 * extent and is safe for the caller to skip.
 */
export function mapDetectionBoxToTile(
  box: { x: number; y: number; width: number; height: number },
  item: SceneItem,
  sourceWidth: number,
  sourceHeight: number,
): { x: number; y: number; width: number; height: number } {
  if (!Number.isFinite(sourceWidth) || !Number.isFinite(sourceHeight) || sourceWidth <= 0 || sourceHeight <= 0)
    return { x: clamp(box.x, 0, 1), y: clamp(box.y, 0, 1), width: clamp(box.width, 0, 1), height: clamp(box.height, 0, 1) };
  const transform = tileTransform(item, sourceWidth, sourceHeight);
  const rawLeft = transform.offsetX + clamp(box.x, 0, 1) * sourceWidth * transform.scaleX;
  const rawTop = transform.offsetY + clamp(box.y, 0, 1) * sourceHeight * transform.scaleY;
  const rawRight = transform.offsetX + clamp(box.x + box.width, 0, 1) * sourceWidth * transform.scaleX;
  const rawBottom = transform.offsetY + clamp(box.y + box.height, 0, 1) * sourceHeight * transform.scaleY;
  const clippedLeft = clamp(Math.min(rawLeft, rawRight), 0, item.width);
  const clippedTop = clamp(Math.min(rawTop, rawBottom), 0, item.height);
  const clippedRight = clamp(Math.max(rawLeft, rawRight), 0, item.width);
  const clippedBottom = clamp(Math.max(rawTop, rawBottom), 0, item.height);
  return {
    x: item.width ? clippedLeft / item.width : 0,
    y: item.height ? clippedTop / item.height : 0,
    width: item.width ? Math.max(0, clippedRight - clippedLeft) / item.width : 0,
    height: item.height ? Math.max(0, clippedBottom - clippedTop) / item.height : 0,
  };
}

export const defaultTelemetryOverlay = (): TelemetryOverlayConfig => ({
  enabled: false,
  fields: ['fps', 'bitrate', 'codec', 'decoder'],
  position: 'bottom-left',
  customX: 0,
  customY: 1,
  textOpacity: .9,
  backgroundEnabled: true,
  backgroundColor: '#000000',
  backgroundOpacity: .45,
  refreshIntervalMs: 1000,
});

export const defaultAudioMeter = (): AudioMeterConfig => ({
  enabled: false,
  orientation: 'vertical',
  position: 'left',
  size: 1,
  opacity: 1,
  customX: .04,
  customY: .5,
  thresholdDbfs: -12,
  alertBorderEnabled: true,
  alertBorderColor: '#ff2d2d',
  alertBorderOpacity: 1,
  alertBorderWidth: 3,
});

export function defaultSourceDecoration(): SourceDecoration {
  return {
    telemetry: defaultTelemetryOverlay(),
    audioMeter: defaultAudioMeter(),
    promotionKinds: { audio: false, motion: false, person: false },
  };
}

export const defaultMonitorView = (): MonitorView => ({
  schemaVersion: 4,
  mode: 'auto',
  largeCount: 0,
  largeSourceIds: [],
  largeRatio: .5,
  telemetry: defaultTelemetryOverlay(),
  fill: 'stretch',
  sourceDecorations: {},
  rotation: { enabled: false, strategy: 'sequential', intervalSeconds: 30, pinnedSourceIds: [] },
  promotion: { allowEventPromotion: false, threshold: .6, holdSeconds: 15, cooldownSeconds: 30 },
  lowPower: { enabled: false, targetFps: 2 },
  panels: { detailsOpen: false, issueCenterExpanded: false },
  localMonitorVolume: 1,
  audioOutput: 'speaker',
  analytics: { showDetectionBoxes: true, showDetectionLabels: false, boxOpacity: .9, boxLineWidth: 2, showInferenceStatus: true },
});

export function sourceDecoration(view: MonitorView, sourceId: string): SourceDecoration {
  const fallback = defaultSourceDecoration();
  const value = view.sourceDecorations[sourceId];
  if (!value) return { ...fallback, telemetry: { ...view.telemetry, fields: [...view.telemetry.fields] } };
  return {
    telemetry: { ...view.telemetry, ...value.telemetry, fields: [...value.telemetry.fields] },
    audioMeter: { ...fallback.audioMeter, ...value.audioMeter },
    promotionKinds: { ...fallback.promotionKinds, ...value.promotionKinds },
    ...(value.fill ? { fill: value.fill } : {}),
  };
}

/**
 * Effective fill for one tile.  An explicit per-source override always wins;
 * otherwise automatic layouts use the monitor-level fill and manual scenes
 * keep the Scene item's own explicit scale mode.
 */
export function resolveFillMode(view: MonitorView, sourceId: string, manualScaleMode: VideoFillMode): VideoFillMode {
  const override = view.sourceDecorations[sourceId]?.fill;
  if (override) return override;
  return view.mode === 'auto' ? view.fill : manualScaleMode;
}

/**
 * Truthful playback label for a live source.  A normal picture is never
 * blanket-labelled "直达"; the actual topology reported by the media plan wins,
 * then the capability delivery mode, and an unknown live path stays generic.
 */
export function playbackTopologyLabel(topology: string | undefined, deliveryMode?: string): string {
  switch (topology) {
  case 'true-direct': return '真直连';
  case 'hybrid': return 'Hybrid 转码';
  case 'gateway-direct': return '网关转发';
  case 'composite': return 'Composite';
  default: break;
  }
  switch (deliveryMode) {
  case 'direct': return '网关直通';
  case 'hybrid': return 'Hybrid 转码';
  case 'composite': return 'Composite';
  default: return '';
  }
}

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));
const finite = (value: unknown, fallback: number) => {
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : fallback;
};
const bounded = (value: unknown, fallback: number, minimum: number, maximum: number) =>
  clamp(finite(value, fallback), minimum, maximum);
const sourceIdentifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9._:-]{1,128}$/.test(value);
const telemetryFields = (value: unknown, fallback: TelemetryField[]) =>
  [...new Set(Array.isArray(value) ? value : fallback)].filter((field): field is TelemetryField =>
    ['fps', 'bitrate', 'codec', 'decoder'].includes(String(field)));
const fillMode = (value: unknown, fallback: VideoFillMode): VideoFillMode =>
  videoFillModes.includes(value as VideoFillMode) ? value as VideoFillMode : fallback;

export function normalizeMonitorView(value: Partial<MonitorView> | null | undefined, sourceCount: number, sourceIds?: string[]): MonitorView {
  const defaults = defaultMonitorView();
  const telemetry = { ...defaults.telemetry, ...(value?.telemetry ?? {}) };
  const rotation = { ...defaults.rotation, ...(value?.rotation ?? {}) };
  const promotion = { ...defaults.promotion, ...(value?.promotion ?? {}) };
  const lowPower = { ...defaults.lowPower, ...(value?.lowPower ?? {}) };
  const panels = { ...defaults.panels, ...(value?.panels ?? {}) };
  const analytics = { ...defaults.analytics, ...(value?.analytics ?? {}) };
  const allowedSourceIds = sourceIds ? new Set(sourceIds.filter(sourceIdentifier)) : null;
  const sourceDecorations: Record<string, SourceDecoration> = {};
  for (const [sourceId, raw] of Object.entries(value?.sourceDecorations ?? {})) {
    if (!sourceIdentifier(sourceId) || (allowedSourceIds && !allowedSourceIds.has(sourceId)) || !raw || typeof raw !== 'object') continue;
    const candidate = raw as Partial<SourceDecoration>;
    const sourceTelemetry = { ...telemetry, ...(candidate.telemetry ?? {}) };
    const rawAudio = (candidate.audioMeter ?? {}) as Partial<AudioMeterConfig>;
    const sourceAudio = { ...defaultAudioMeter(), ...rawAudio };
    // Stored v4 meters defaulted to the top-left corner, which covered the
    // "直达" tile label.  Migrate those to the OBS-style left rail once.
    const legacyTopLeft = !('orientation' in rawAudio) && sourceAudio.position === 'top-left';
    sourceDecorations[sourceId] = {
      telemetry: {
        ...sourceTelemetry,
        fields: telemetryFields(sourceTelemetry.fields, defaults.telemetry.fields),
        position: ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'custom'].includes(sourceTelemetry.position) ? sourceTelemetry.position : 'bottom-left',
        customX: bounded(sourceTelemetry.customX, defaults.telemetry.customX, 0, 1), customY: bounded(sourceTelemetry.customY, defaults.telemetry.customY, 0, 1),
        textOpacity: bounded(sourceTelemetry.textOpacity, defaults.telemetry.textOpacity, 0, 1), backgroundOpacity: bounded(sourceTelemetry.backgroundOpacity, defaults.telemetry.backgroundOpacity, 0, 1),
        refreshIntervalMs: bounded(Math.trunc(finite(sourceTelemetry.refreshIntervalMs, defaults.telemetry.refreshIntervalMs)), defaults.telemetry.refreshIntervalMs, 500, 10000),
        backgroundColor: /^#[0-9a-f]{6}$/i.test(sourceTelemetry.backgroundColor) ? sourceTelemetry.backgroundColor : '#000000',
      },
      audioMeter: {
        ...sourceAudio,
        orientation: sourceAudio.orientation === 'horizontal' ? 'horizontal' : 'vertical',
        position: legacyTopLeft ? 'left'
          : (['left', 'right', 'top-left', 'top-right', 'bottom-left', 'bottom-right', 'custom'] as const)
            .includes(sourceAudio.position) ? sourceAudio.position : 'left',
        size: bounded(sourceAudio.size, 1, .3, 2),
        opacity: bounded(sourceAudio.opacity, 1, .1, 1),
        customX: bounded(sourceAudio.customX, .04, 0, 1),
        customY: bounded(sourceAudio.customY, .5, 0, 1),
        thresholdDbfs: bounded(sourceAudio.thresholdDbfs, -12, -120, 0),
        alertBorderOpacity: bounded(sourceAudio.alertBorderOpacity, 1, 0, 1),
        alertBorderWidth: bounded(Math.trunc(finite(sourceAudio.alertBorderWidth, 3)), 3, 1, 12),
        alertBorderColor: /^#[0-9a-f]{6}$/i.test(sourceAudio.alertBorderColor) ? sourceAudio.alertBorderColor : '#ff2d2d',
      },
      promotionKinds: {
        audio: Boolean(candidate.promotionKinds?.audio),
        motion: Boolean(candidate.promotionKinds?.motion),
        person: Boolean(candidate.promotionKinds?.person),
      },
      ...(candidate.fill ? { fill: fillMode(candidate.fill, defaults.fill) } : {}),
    };
  }
  return {
    schemaVersion: 4,
    mode: value?.mode === 'manual' ? 'manual' : 'auto',
    largeCount: clamp(Math.trunc(value?.largeCount ?? 0), 0, clamp(sourceCount, 0, 16)),
    largeSourceIds: [...new Set((Array.isArray(value?.largeSourceIds) ? value?.largeSourceIds : []).filter(sourceIdentifier))].slice(0, 16),
    largeRatio: bounded(value?.largeRatio, .5, .1, .9),
    fill: fillMode(value?.fill, defaults.fill),
    telemetry: {
      ...telemetry,
      fields: telemetryFields(telemetry.fields, defaults.telemetry.fields),
      position: ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'custom'].includes(telemetry.position)
        ? telemetry.position : 'bottom-left',
      customX: bounded(telemetry.customX, defaults.telemetry.customX, 0, 1), customY: bounded(telemetry.customY, defaults.telemetry.customY, 0, 1),
      textOpacity: bounded(telemetry.textOpacity, defaults.telemetry.textOpacity, 0, 1),
      backgroundOpacity: bounded(telemetry.backgroundOpacity, defaults.telemetry.backgroundOpacity, 0, 1),
      refreshIntervalMs: bounded(Math.trunc(finite(telemetry.refreshIntervalMs, defaults.telemetry.refreshIntervalMs)), defaults.telemetry.refreshIntervalMs, 500, 10000),
      backgroundColor: /^#[0-9a-f]{6}$/i.test(telemetry.backgroundColor) ? telemetry.backgroundColor : '#000000',
    },
    sourceDecorations,
    rotation: {
      ...rotation,
      strategy: rotation.strategy === 'random' ? 'random' : 'sequential',
      intervalSeconds: clamp(Math.trunc(rotation.intervalSeconds), 5, 24 * 60 * 60),
      pinnedSourceIds: [...new Set((Array.isArray(rotation.pinnedSourceIds) ? rotation.pinnedSourceIds : []).filter(sourceIdentifier))].slice(0, 16),
    },
    promotion: {
      ...promotion,
      threshold: clamp(Number(promotion.threshold), 0, 1),
      holdSeconds: clamp(Math.trunc(promotion.holdSeconds), 1, 3600),
      cooldownSeconds: clamp(Math.trunc(promotion.cooldownSeconds), 0, 24 * 60 * 60),
    },
    lowPower: { ...lowPower, targetFps: clamp(Number(lowPower.targetFps), .5, 30) },
    panels: { detailsOpen: Boolean(panels.detailsOpen), issueCenterExpanded: Boolean(panels.issueCenterExpanded) },
    localMonitorVolume: bounded(value?.localMonitorVolume, 1, 0, 1),
    audioOutput: value?.audioOutput === 'meter-only' ? 'meter-only' : 'speaker',
    analytics: {
      showDetectionBoxes: Boolean(analytics.showDetectionBoxes),
      showDetectionLabels: Boolean(analytics.showDetectionLabels),
      boxOpacity: clamp(Number(analytics.boxOpacity), 0, 1),
      boxLineWidth: clamp(Number(analytics.boxLineWidth), 1, 8),
      showInferenceStatus: Boolean(analytics.showInferenceStatus),
    },
  };
}

const LAYOUT_UNITS = 12;

/** Large tile span in fine layout units; small tiles always span LAYOUT_UNITS. */
export function largeTileSpan(ratio: number): number {
  const safe = clamp(Number.isFinite(ratio) ? ratio : .5, .1, .9);
  return clamp(Math.round(LAYOUT_UNITS / safe), LAYOUT_UNITS, LAYOUT_UNITS * 10);
}

export interface WallRectangle { x: number; y: number; width: number; height: number }

/**
 * Squarified treemap.  A shelf/skyline packer leaves an unused slot or a short
 * trailing row whenever the tile count does not divide the grid, which reads as
 * an unexplained black gap.  A treemap partitions the canvas exactly, so the
 * wall is always fully covered while each tile keeps an area proportional to
 * the requested large/small ratio.  It is a pure function of the areas and the
 * canvas, so laying out an already-laid-out scene is a stable fixed point.
 */
export function squarifiedLayout(areas: number[], width: number, height: number): WallRectangle[] {
  const total = areas.reduce((sum, area) => sum + Math.max(0, area), 0);
  if (!areas.length) return [];
  if (total <= 0 || width <= 0 || height <= 0) return areas.map(() => ({ x: 0, y: 0, width, height }));
  const scaled = areas.map((area) => Math.max(0, area) * (width * height) / total);
  const rectangles: WallRectangle[] = new Array(areas.length);
  let x = 0;
  let y = 0;
  let availableWidth = width;
  let availableHeight = height;
  let start = 0;
  while (start < scaled.length) {
    const vertical = availableWidth >= availableHeight;
    const shortSide = Math.max(1e-6, vertical ? availableHeight : availableWidth);
    let rowSum = 0;
    let end = start;
    let bestWorst = Number.POSITIVE_INFINITY;
    while (end < scaled.length) {
      const candidateSum = rowSum + scaled[end];
      const thickness = candidateSum / shortSide;
      let worst = 0;
      for (let index = start; index <= end; index += 1) {
        const length = thickness > 0 ? scaled[index] / thickness : 0;
        const ratio = length > 0 ? Math.max(thickness / length, length / thickness) : Number.POSITIVE_INFINITY;
        if (ratio > worst) worst = ratio;
      }
      if (worst <= bestWorst) { bestWorst = worst; rowSum = candidateSum; end += 1; }
      else break;
    }
    if (end === start) { end = start + 1; rowSum = scaled[start]; }
    const thickness = Math.max(1e-6, rowSum / shortSide);
    let offset = 0;
    for (let index = start; index < end; index += 1) {
      const length = scaled[index] / thickness;
      rectangles[index] = vertical
        ? { x, y: y + offset, width: thickness, height: length }
        : { x: x + offset, y, width: length, height: thickness };
      offset += length;
    }
    if (vertical) { x += thickness; availableWidth -= thickness; }
    else { y += thickness; availableHeight -= thickness; }
    start = end;
  }
  return rectangles;
}

/** Generate ordinary Scene v5 item rectangles; MonitorView never becomes a second scene schema. */
export function applyAutomaticLayout(scene: SceneDocument, viewValue: Partial<MonitorView>): SceneDocument {
  const visible = scene.items.filter((item) => item.visible).slice(0, 16);
  if (!visible.length) return scene;
  const view = normalizeMonitorView(viewValue, visible.length, scene.sources.map((source) => source.id));
  if (view.mode !== 'auto') return scene;
  const sourceIds = visible.map((item) => item.sourceId);
  const chosenLarge = view.largeSourceIds.filter((id) => sourceIds.includes(id)).slice(0, view.largeCount);
  for (const id of sourceIds) if (chosenLarge.length < view.largeCount && !chosenLarge.includes(id)) chosenLarge.push(id);
  const large = new Set(chosenLarge);
  const smallIds = sourceIds.filter((id) => !large.has(id));
  const bigSpan = largeTileSpan(view.largeRatio);
  const ordered = [...chosenLarge, ...smallIds];
  // Large tiles lead so the focus block lands in the top-left of the canvas.
  const areas = [...chosenLarge.map(() => bigSpan * bigSpan), ...smallIds.map(() => LAYOUT_UNITS * LAYOUT_UNITS)];
  const rectangles = squarifiedLayout(areas, scene.canvas.width, scene.canvas.height);
  const rectangleBySource = new Map(ordered.map((sourceId, index) => [sourceId, rectangles[index]] as const));
  const items = scene.items.map((item): SceneItem => {
    const rectangle = rectangleBySource.get(item.sourceId);
    if (!rectangle) return item;
    // Automatic layouts own the fill so Direct and Composite render the same
    // effective scene; explicit per-source overrides still win.
    return { ...item, ...rectangle, scaleMode: resolveFillMode(view, item.sourceId, item.scaleMode) };
  });
  return { ...scene, items };
}

export interface LowPowerSelection { profile: CameraProfile | null; targetMet: boolean; reason: string }

export function selectLowPowerProfile(profiles: CameraProfile[], targetFps: number): LowPowerSelection {
  if (!profiles.length) return { profile: null, targetMet: false, reason: 'no_profile' };
  const target = clamp(targetFps, .5, 30);
  const cost = (profile: CameraProfile) => (profile.width || 1) * (profile.height || 1) * Math.max(profile.fps, .1);
  const suitable = profiles.filter((profile) => profile.fps > 0 && profile.fps <= target)
    .sort((a, b) => cost(a) - cost(b));
  if (suitable.length) return { profile: suitable[0], targetMet: true, reason: '' };
  const lowest = [...profiles].sort((a, b) => (a.fps || 999) - (b.fps || 999) || cost(a) - cost(b))[0];
  return { profile: lowest, targetMet: false, reason: 'no_low_frame_rate_profile' };
}

export function validDetectionSignal(signal: DetectionSignal): boolean {
  const boxesValid = !signal.boxes || (signal.kind === 'person' && signal.boxes.length <= 16 && signal.boxes.every((box) =>
    [box.x, box.y, box.width, box.height].every((value) => Number.isFinite(value) && value >= 0 && value <= 1) &&
    box.x + box.width <= 1 && box.y + box.height <= 1));
  return (signal.schemaVersion === 1 || signal.schemaVersion === 2) && /^[A-Za-z0-9._-]{1,64}$/.test(signal.cameraId) &&
    /^[A-Za-z0-9._-]{1,64}$/.test(signal.profileId) && ['motion', 'scene-change', 'person'].includes(signal.kind) &&
    ['camera', 'browser', 'server', 'external'].includes(signal.source) &&
    Number.isInteger(signal.occurredAt) && signal.occurredAt > 0 && signal.confidence >= 0 && signal.confidence <= 1 && boxesValid &&
    (signal.schemaVersion === 1 || (typeof signal.signalId === 'string' && /^[A-Za-z0-9._:-]{8,128}$/.test(signal.signalId))) &&
    (!signal.signalId || /^[A-Za-z0-9._:-]{8,128}$/.test(signal.signalId)) &&
    (!signal.modelId || /^[A-Za-z0-9._-]{1,64}$/.test(signal.modelId)) &&
    (!signal.modelVersion || /^[A-Za-z0-9._-]{1,32}$/.test(signal.modelVersion)) &&
    (!signal.modelSha256 || /^[0-9a-f]{64}$/i.test(signal.modelSha256));
}

export interface PromotionPolicyInput {
  allowEventPromotion: boolean;
  promotionThreshold: number;
  promotionHoldSeconds: number;
  promotionCooldownSeconds: number;
  forceAnalyticsAlwaysOn: boolean;
}

export function evaluatePromotion(signal: DetectionSignal, policy: PromotionPolicyInput | undefined, options: {
  enabled: boolean; threshold: number; holdSeconds: number; cooldownSeconds: number;
  lowPowerEnabled: boolean; now: number; cooldownUntil: number;
}): { accepted: boolean; reason: string; holdUntil: number; cooldownUntil: number } {
  const rejected = (reason: string) => ({ accepted: false, reason, holdUntil: 0, cooldownUntil: options.cooldownUntil });
  if (!options.enabled || !policy?.allowEventPromotion) return rejected('promotion_disabled');
  if (!validDetectionSignal(signal)) return rejected('invalid_signal');
  if (signal.confidence < Math.max(options.threshold, policy.promotionThreshold)) return rejected('below_threshold');
  if (options.lowPowerEnabled && signal.source !== 'camera' && !policy.forceAnalyticsAlwaysOn)
    return rejected('low_power_software_analytics_disabled');
  if (options.cooldownUntil > options.now) return rejected('cooldown_active');
  const holdSeconds = Math.max(options.holdSeconds, policy.promotionHoldSeconds);
  const cooldownSeconds = Math.max(options.cooldownSeconds, policy.promotionCooldownSeconds);
  return {
    accepted: true, reason: '', holdUntil: options.now + holdSeconds * 1000,
    cooldownUntil: options.now + (holdSeconds + cooldownSeconds) * 1000,
  };
}

export function createShuffleBag<T>(items: T[], random: () => number = Math.random): T[] {
  const bag = [...items];
  for (let index = bag.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(random() * (index + 1));
    [bag[index], bag[swap]] = [bag[swap], bag[index]];
  }
  return bag;
}

export function nextRotationWindow(
  sourceIds: string[], current: string[], largeCount: number, pinnedIds: string[],
  strategy: 'sequential' | 'random', bag: string[] = [], random: () => number = Math.random,
): { selection: string[]; bag: string[] } {
  const uniqueSources = [...new Set(sourceIds)];
  const pinned = [...new Set(pinnedIds)].filter((id) => uniqueSources.includes(id)).slice(0, largeCount);
  const candidates = uniqueSources.filter((id) => !pinned.includes(id));
  const count = Math.max(0, Math.min(largeCount - pinned.length, candidates.length));
  if (strategy === 'sequential') {
    const previous = current.filter((id) => candidates.includes(id));
    const start = previous.length ? (candidates.indexOf(previous.at(-1)!) + 1) % Math.max(candidates.length, 1) : 0;
    return { selection: [...pinned, ...Array.from({ length: count }, (_, index) => candidates[(start + index) % candidates.length]).filter(Boolean)], bag: [] };
  }
  const remaining = bag.filter((id) => candidates.includes(id));
  const selected: string[] = [];
  while (selected.length < count && candidates.length) {
    if (!remaining.length) remaining.push(...createShuffleBag(candidates.filter((id) => !selected.includes(id)), random));
    const next = remaining.shift();
    if (next && !selected.includes(next)) selected.push(next);
  }
  return { selection: [...pinned, ...selected], bag: remaining };
}
