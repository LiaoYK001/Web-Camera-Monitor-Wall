export type PwaUpdateState = 'unsupported' | 'installing' | 'cached' | 'error';
export type PwaInstallState = 'installed' | 'installable' | 'browser-only';

interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let installPrompt: InstallPromptEvent | null = null;

function announce(state: PwaUpdateState) {
  window.dispatchEvent(new CustomEvent<PwaUpdateState>('webobs:pwa-state', { detail: state }));
}

function announceInstall(state: PwaInstallState) {
  window.dispatchEvent(new CustomEvent<PwaInstallState>('webobs:pwa-install-state', { detail: state }));
}

export function currentPwaInstallState(): PwaInstallState {
  return window.matchMedia('(display-mode: standalone)').matches ? 'installed' :
    installPrompt ? 'installable' : 'browser-only';
}

export async function installPwa(): Promise<PwaInstallState> {
  const prompt = installPrompt;
  if (!prompt) return currentPwaInstallState();
  installPrompt = null;
  await prompt.prompt();
  const choice = await prompt.userChoice;
  const state = choice.outcome === 'accepted' ? 'installed' : 'browser-only';
  announceInstall(state);
  return state;
}

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  installPrompt = event as InstallPromptEvent;
  announceInstall('installable');
});
window.addEventListener('appinstalled', () => {
  installPrompt = null;
  announceInstall('installed');
});

export async function registerPwaRuntime(): Promise<void> {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) {
    announce('unsupported');
    return;
  }
  try {
    const { registerSW } = await import('virtual:pwa-register');
    registerSW({
      immediate: true,
      onRegisteredSW(_url, registration) {
        announce(navigator.serviceWorker.controller ? 'cached' : 'installing');
        if (!registration) return;
        registration.addEventListener('updatefound', () => announce('installing'));
      },
      onOfflineReady() { announce('cached'); },
      onNeedRefresh() { announce('installing'); },
      onRegisterError() { announce('error'); },
    });
  } catch {
    announce('error');
  }
}
