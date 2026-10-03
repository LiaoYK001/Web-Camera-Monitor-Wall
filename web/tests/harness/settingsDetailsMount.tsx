import { createRoot } from 'react-dom/client';
import AccountWorkspace from '../../src/AccountWorkspace';
import DesktopSettings from '../../src/DesktopSettings';
import AboutSettings from '../../src/AboutSettings';

export function mountSettingsDetails(kind: 'account' | 'desktop', host: HTMLElement) {
  const root = createRoot(host);
  root.render(kind === 'account' ? <AccountWorkspace onAdmin={() => { host.dataset.adminOpened = 'true'; }} /> : <><DesktopSettings /><AboutSettings /></>);
  return { unmount: () => root.unmount() };
}
