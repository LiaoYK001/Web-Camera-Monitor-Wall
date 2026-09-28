export function canLeaveWorkspace(): boolean {
  return window.dispatchEvent(new Event('webobs:before-navigate', { cancelable: true }));
}
