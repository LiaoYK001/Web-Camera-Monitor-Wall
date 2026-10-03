// Real application and authentication gate; protocol fixtures are supplied by Playwright.
import { createRoot } from 'react-dom/client';
import App from '../../src/App';
import LoginGate from '../../src/LoginGate';
import '../../src/styles.css';
import '../../src/interactions.css';
createRoot(document.getElementById('root')!).render(new URLSearchParams(location.search).has('seed')
  ? <p>Encrypted cache setup</p> : <LoginGate><App /></LoginGate>);
