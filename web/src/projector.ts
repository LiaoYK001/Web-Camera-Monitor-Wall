/**
 * F6-07 projector window.
 *
 * The detachable small window is not a second copy of the monitor workspace: it
 * renders the final picture only, the way OBS does with
 * "Scenes -> Open Scene Projector -> New Window".  The route is therefore
 * resolved before the workspace shell mounts, and the projector mounts only the
 * preview surface.
 */
export type ProjectorMode = 'direct' | 'composite';

/** Browser window name; re-opening the same mode reuses the existing window. */
export function projectorWindowName(mode: ProjectorMode): string {
  return `webobs-projector-${mode}`;
}

export function projectorHash(mode: ProjectorMode): string {
  return mode === 'composite' ? '#projector-composite' : '#projector';
}

/** Resolves the projector route; `null` means "render the normal workspace". */
export function projectorModeFromHash(hash: string): ProjectorMode | null {
  const route = hash.replace(/^#\/?/, '').split(/[/?]/, 1)[0];
  if (route === 'projector') return 'direct';
  if (route === 'projector-composite') return 'composite';
  return null;
}

/**
 * Same-origin and same-path so the session cookie, CSP and media origin keep
 * matching the wall; the query string is dropped on purpose.
 */
export function projectorUrl(mode: ProjectorMode, location: Pick<Location, 'pathname'> = window.location): string {
  return `${location.pathname}${projectorHash(mode)}`;
}

const projectorFeatures = 'popup=yes,width=960,height=540,menubar=no,toolbar=no,location=no,status=no';

export function openProjectorWindow(mode: ProjectorMode): Window | null {
  return window.open(projectorUrl(mode), projectorWindowName(mode), projectorFeatures);
}
