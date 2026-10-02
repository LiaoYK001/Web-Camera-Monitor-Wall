declare global { interface Window { webobsAndroidForeground?: boolean } }

/** Android Activity lifecycle supplements Page Visibility on older WebViews. */
export function isPageVisible(): boolean {
  return !document.hidden && window.webobsAndroidForeground !== false;
}

export function subscribePageVisibility(changed: () => void): () => void {
  document.addEventListener('visibilitychange', changed);
  window.addEventListener('webobs:visibility', changed);
  return () => {
    document.removeEventListener('visibilitychange', changed);
    window.removeEventListener('webobs:visibility', changed);
  };
}
