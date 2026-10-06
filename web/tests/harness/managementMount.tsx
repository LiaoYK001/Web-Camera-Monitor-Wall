import { createRoot } from 'react-dom/client';
import ClientsPanel from '../../src/ClientsPanel';
import ClusterAdmin from '../../src/ClusterAdmin';

export type ManagementSurface = 'clients' | 'cluster';

/**
 * Mounts the management surfaces in isolation so their own recovery behaviour
 * (per-resource locks, deadline phases, read-only reconciliation, draft guards)
 * can be exercised without the workspace shell or a real control server.
 */
export function mountManagement(surface: ManagementSurface, host: HTMLElement) {
  const root = createRoot(host);
  root.render(surface === 'clients'
    ? <ClientsPanel onBack={() => { host.dataset.leftWorkspace = 'true'; }} />
    : <ClusterAdmin />);
  return { unmount: () => root.unmount() };
}

const host = document.getElementById('root');
const requested = new URLSearchParams(window.location.search).get('surface');
if (host && (requested === 'clients' || requested === 'cluster')) mountManagement(requested, host);
