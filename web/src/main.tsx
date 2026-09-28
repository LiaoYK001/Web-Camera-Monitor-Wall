import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import LoginGate from './LoginGate';
import ProjectorView from './ProjectorView';
import { projectorModeFromHash } from './projector';
import { registerPwaRuntime } from './pwaRuntime';
import './styles.css';

window.trustedTypes?.createPolicy('default', {
  createHTML: (input) => {
    if (input !== '') throw new TypeError('Dynamic HTML is not allowed');
    return input;
  },
  createScript: () => { throw new TypeError('Dynamic scripts are not allowed'); },
  createScriptURL: (input) => {
    const url = new URL(input, window.location.href);
    if (url.protocol !== 'blob:' && url.origin !== window.location.origin)
      throw new TypeError('Cross-origin script URLs are not allowed');
    return url.href;
  },
});

void registerPwaRuntime();

// F6-07: the projector route mounts the picture surface only, so the detached
// window never boots a second copy of the workspace shell.
const projectorMode = projectorModeFromHash(window.location.hash);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LoginGate>{projectorMode ? <ProjectorView mode={projectorMode} /> : <App />}</LoginGate>
  </StrictMode>,
);
