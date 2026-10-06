import { isSupportedSceneSchema } from './sceneSchema';
import type { SceneCanvas, SceneDocument, StudioDocument } from './types';

/**
 * Compatibility boundary for Studio documents.
 *
 * The server owns scene-file migration (docs/scene-schema-v4.md: the loader accepts
 * v0-v3, adds safe defaults, validates the full result, and refuses invalid or future
 * versions).  The shell mirrors that policy for the documents it actually receives and
 * stores locally, because a forced security replacement or an offline cache can hand it
 * a document written by an older core:
 *
 *  - a collection without the transition block (partial/older payload, or a cached
 *    snapshot written before the field existed) would otherwise crash the workspace;
 *  - a scene that still carries a pre-v5 schema number is upgraded to the baseline v5
 *    shape with explicit safe defaults.
 *
 * Current documents (scene schema 5/6, valid transition) are returned untouched, and an
 * unknown or future schema is never rewritten - it stays for the strict validators to
 * reject.  Nothing here invents content: no name, source, URL or credential is added.
 */
const LEGACY_SCENE_SCHEMA_MAX = 4;
const BASELINE_SCENE_SCHEMA = 5;
const CANVAS_MIN = 16;
const CANVAS_MAX = 8192;
const SCENE_ID = /^[A-Za-z0-9._-]{1,64}$/;
const COLOR = /^#[0-9a-fA-F]{6}$/;

const evenSize = (value: unknown, fallback: number): number => {
  if (!Number.isSafeInteger(value) || (value as number) < CANVAS_MIN || (value as number) > CANVAS_MAX) return fallback;
  const size = value as number;
  return size - (size % 2);
};

/** Baseline canvas: older documents used `background`, current ones `backgroundColor`. */
function canvasDefaults(value: unknown): SceneCanvas {
  const canvas = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const color = [canvas.backgroundColor, canvas.background]
    .find((candidate): candidate is string => typeof candidate === 'string' && COLOR.test(candidate));
  return { width: evenSize(canvas.width, 1280), height: evenSize(canvas.height, 720), backgroundColor: color ?? '#000000' };
}

function legacySceneEligible(scene: Record<string, unknown>): boolean {
  return typeof scene.id === 'string' && SCENE_ID.test(scene.id) &&
    typeof scene.name === 'string' && scene.name.trim().length > 0 && scene.name.length <= 128 &&
    Number.isSafeInteger(scene.revision) && (scene.revision as number) >= 0 &&
    Array.isArray(scene.sources) && scene.sources.length <= 256 &&
    Array.isArray(scene.items) && scene.items.length <= 512 &&
    (scene.sources as unknown[]).every((source) => Boolean(source) && typeof source === 'object' &&
      typeof (source as { id?: unknown }).id === 'string' && SCENE_ID.test((source as { id: string }).id));
}

/** Upgrades a pre-v5 scene to the baseline shape; anything else is passed through unchanged. */
export function normalizeSceneDocument<T>(scene: T): T {
  if (!scene || typeof scene !== 'object') return scene;
  const value = scene as Record<string, unknown>;
  if (isSupportedSceneSchema(value.schemaVersion)) return scene;
  if (!Number.isInteger(value.schemaVersion) || (value.schemaVersion as number) < 0 ||
      (value.schemaVersion as number) > LEGACY_SCENE_SCHEMA_MAX) return scene;
  if (!legacySceneEligible(value)) return scene;
  return { ...value, schemaVersion: BASELINE_SCENE_SCHEMA, canvas: canvasDefaults(value.canvas) } as T;
}

export function normalizeStudioDocument(studio: StudioDocument): StudioDocument {
  const scenes = Array.isArray(studio.scenes) ? studio.scenes.map(normalizeSceneDocument) : studio.scenes;
  const transition = studio.transition;
  const kind = transition?.kind === 'fade' ? 'fade' : 'cut';
  const durationMs = transition && Number.isFinite(transition.durationMs)
    ? Math.min(Math.max(Math.trunc(transition.durationMs), 0), 10_000) : 0;
  const unchanged = transition?.kind === kind && transition?.durationMs === durationMs;
  return { ...studio, transition: unchanged ? transition : { kind, durationMs }, scenes };
}
