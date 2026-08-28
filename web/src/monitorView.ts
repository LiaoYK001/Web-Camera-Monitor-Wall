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
  schemaVersion: 1;
  mode: 'auto' | 'manual';
  largeCount: number;
  largeSourceIds: string[];
  telemetry: TelemetryOverlayConfig;
  rotation: RotationConfig;
  promotion: PromotionConfig;
  lowPower: LowPowerConfig;
}

export interface DetectionSignal {
  schemaVersion: 1;
  cameraId: string;
  profileId: string;
  kind: 'motion' | 'scene-change' | 'person';
  occurredAt: number;
  confidence: number;
  boxes?: Array<{ x: number; y: number; width: number; height: number }>;
  source: 'camera' | 'browser' | 'server' | 'external';
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

export const defaultMonitorView = (): MonitorView => ({
  schemaVersion: 1,
  mode: 'auto',
  largeCount: 0,
  largeSourceIds: [],
  telemetry: defaultTelemetryOverlay(),
  rotation: { enabled: false, strategy: 'sequential', intervalSeconds: 30, pinnedSourceIds: [] },
  promotion: { allowEventPromotion: false, threshold: .6, holdSeconds: 15, cooldownSeconds: 30 },
  lowPower: { enabled: false, targetFps: 2 },
});

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));

export function normalizeMonitorView(value: Partial<MonitorView> | null | undefined, sourceCount: number): MonitorView {
  const defaults = defaultMonitorView();
  const telemetry = { ...defaults.telemetry, ...(value?.telemetry ?? {}) };
  const rotation = { ...defaults.rotation, ...(value?.rotation ?? {}) };
  const promotion = { ...defaults.promotion, ...(value?.promotion ?? {}) };
  const lowPower = { ...defaults.lowPower, ...(value?.lowPower ?? {}) };
  return {
    schemaVersion: 1,
    mode: value?.mode === 'manual' ? 'manual' : 'auto',
    largeCount: clamp(Math.trunc(value?.largeCount ?? 0), 0, clamp(sourceCount, 0, 16)),
    largeSourceIds: [...new Set(value?.largeSourceIds ?? [])].slice(0, 16),
    telemetry: {
      ...telemetry,
      fields: [...new Set(telemetry.fields)].filter((field): field is TelemetryField =>
        ['fps', 'bitrate', 'codec', 'decoder'].includes(field)),
      position: ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'custom'].includes(telemetry.position)
        ? telemetry.position : 'bottom-left',
      customX: clamp(Number(telemetry.customX), 0, 1), customY: clamp(Number(telemetry.customY), 0, 1),
      textOpacity: clamp(Number(telemetry.textOpacity), 0, 1),
      backgroundOpacity: clamp(Number(telemetry.backgroundOpacity), 0, 1),
      refreshIntervalMs: clamp(Math.trunc(telemetry.refreshIntervalMs), 500, 10000),
      backgroundColor: /^#[0-9a-f]{6}$/i.test(telemetry.backgroundColor) ? telemetry.backgroundColor : '#000000',
    },
    rotation: {
      ...rotation,
      strategy: rotation.strategy === 'random' ? 'random' : 'sequential',
      intervalSeconds: clamp(Math.trunc(rotation.intervalSeconds), 5, 24 * 60 * 60),
      pinnedSourceIds: [...new Set(rotation.pinnedSourceIds)].slice(0, 16),
    },
    promotion: {
      ...promotion,
      threshold: clamp(Number(promotion.threshold), 0, 1),
      holdSeconds: clamp(Math.trunc(promotion.holdSeconds), 1, 3600),
      cooldownSeconds: clamp(Math.trunc(promotion.cooldownSeconds), 0, 24 * 60 * 60),
    },
    lowPower: { ...lowPower, targetFps: clamp(Number(lowPower.targetFps), .5, 30) },
  };
}

interface CellPlacement { sourceId: string; column: number; row: number; columns: number; rows: number; large: boolean }

function candidatePlacement(sourceIds: string[], large: Set<string>, columns: number, rows: number, portrait: boolean): CellPlacement[] | null {
  if (columns === 1 && large.size > 0 && large.size < sourceIds.length) return null;
  const occupied = Array.from({ length: rows }, () => Array(columns).fill(false));
  const result: CellPlacement[] = [];
  const place = (sourceId: string, largeItem: boolean): boolean => {
    const spanColumns = largeItem ? (portrait || columns <= 2 ? columns : 2) : 1;
    const spanRows = largeItem ? (portrait || columns <= 2 ? 1 : 2) : 1;
    for (let row = 0; row <= rows - spanRows; row += 1) for (let column = 0; column <= columns - spanColumns; column += 1) {
      let free = true;
      for (let y = row; y < row + spanRows; y += 1) for (let x = column; x < column + spanColumns; x += 1)
        if (occupied[y][x]) free = false;
      if (!free) continue;
      for (let y = row; y < row + spanRows; y += 1) for (let x = column; x < column + spanColumns; x += 1)
        occupied[y][x] = true;
      result.push({ sourceId, column, row, columns: spanColumns, rows: spanRows, large: largeItem });
      return true;
    }
    return false;
  };
  for (const sourceId of sourceIds.filter((id) => large.has(id))) if (!place(sourceId, true)) return null;
  for (const sourceId of sourceIds.filter((id) => !large.has(id))) if (!place(sourceId, false)) return null;
  return result;
}

/** Generate ordinary Scene v5 item rectangles; MonitorView never becomes a second scene schema. */
export function applyAutomaticLayout(scene: SceneDocument, viewValue: Partial<MonitorView>): SceneDocument {
  const visible = scene.items.filter((item) => item.visible).slice(0, 16);
  if (!visible.length) return scene;
  const view = normalizeMonitorView(viewValue, visible.length);
  if (view.mode !== 'auto') return scene;
  const sourceIds = visible.map((item) => item.sourceId);
  const chosenLarge = view.largeSourceIds.filter((id) => sourceIds.includes(id)).slice(0, view.largeCount);
  for (const id of sourceIds) if (chosenLarge.length < view.largeCount && !chosenLarge.includes(id)) chosenLarge.push(id);
  const large = new Set(chosenLarge);
  const portrait = scene.canvas.height > scene.canvas.width;
  let best: { score: number; placements: CellPlacement[]; columns: number; rows: number } | null = null;
  for (let columns = 1; columns <= Math.min(8, visible.length); columns += 1) {
    for (let rows = 1; rows <= 16; rows += 1) {
      const placements = candidatePlacement(sourceIds, large, columns, rows, portrait);
      if (!placements) continue;
      const used = placements.reduce((sum, item) => sum + item.columns * item.rows, 0);
      const empty = columns * rows - used;
      const cellRatio = (scene.canvas.width / columns) / (scene.canvas.height / rows);
      const ratioError = Math.abs(Math.log(cellRatio / (16 / 9)));
      const movement = placements.reduce((sum, placement) => {
        const old = visible.find((item) => item.sourceId === placement.sourceId)!;
        const x = placement.column * scene.canvas.width / columns;
        const y = placement.row * scene.canvas.height / rows;
        return sum + Math.abs(x - old.x) / scene.canvas.width + Math.abs(y - old.y) / scene.canvas.height;
      }, 0);
      const score = empty * 100 + ratioError * 10 + movement;
      if (!best || score < best.score) best = { score, placements, columns, rows };
    }
  }
  if (!best) return scene;
  const placementBySource = new Map(best.placements.map((placement) => [placement.sourceId, placement]));
  const items = scene.items.map((item): SceneItem => {
    const placement = placementBySource.get(item.sourceId);
    if (!placement) return item;
    return {
      ...item,
      x: placement.column * scene.canvas.width / best!.columns,
      y: placement.row * scene.canvas.height / best!.rows,
      width: placement.columns * scene.canvas.width / best!.columns,
      height: placement.rows * scene.canvas.height / best!.rows,
    };
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
  return signal.schemaVersion === 1 && /^[A-Za-z0-9._-]{1,64}$/.test(signal.cameraId) &&
    /^[A-Za-z0-9._-]{1,64}$/.test(signal.profileId) && ['motion', 'scene-change', 'person'].includes(signal.kind) &&
    Number.isFinite(signal.occurredAt) && signal.occurredAt > 0 && signal.confidence >= 0 && signal.confidence <= 1 &&
    (!signal.boxes || signal.boxes.length <= 64 && signal.boxes.every((box) =>
      [box.x, box.y, box.width, box.height].every((value) => Number.isFinite(value) && value >= 0 && value <= 1) &&
      box.x + box.width <= 1 && box.y + box.height <= 1));
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
