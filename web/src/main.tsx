import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import LoginGate from './LoginGate';
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LoginGate><App /></LoginGate>
  </StrictMode>,
);
