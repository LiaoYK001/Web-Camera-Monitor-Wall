export interface PlaybackVisibility {
  lowPowerEnabled: boolean;
  documentVisible: boolean;
  tileIntersecting: boolean;
}

/** Low-power mode owns suspension; normal monitoring must not stop just because the page is partially occluded. */
export function shouldRunPlayback(state: PlaybackVisibility): boolean {
  return !state.lowPowerEnabled || (state.documentVisible && state.tileIntersecting);
}

export function observeTileVisibility(element: Element, changed: (visible: boolean) => void): () => void {
  if (!('IntersectionObserver' in window)) {
    changed(true);
    return () => undefined;
  }
  const observer = new IntersectionObserver((entries) => {
    const entry = entries[0];
    changed(Boolean(entry?.isIntersecting && entry.intersectionRatio > 0));
  }, { threshold: [0, .01] });
  observer.observe(element);
  return () => observer.disconnect();
}
