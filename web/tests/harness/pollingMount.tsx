import { createRoot } from 'react-dom/client';
import SystemStatus from '../../src/SystemStatus';
import ClientsPanel from '../../src/ClientsPanel';
import AnalyticsWorkspace from '../../src/AnalyticsWorkspace';
import ProjectorView from '../../src/ProjectorView';
import ProgramPreview from '../../src/ProgramPreview';

export function mountPollingPage(kind: 'system' | 'clients' | 'analytics' | 'projector' | 'program', host: HTMLElement) {
  const root = createRoot(host);
  const back = () => undefined;
  root.render(kind === 'system' ? <SystemStatus onBack={back} />
    : kind === 'clients' ? <ClientsPanel onBack={back} />
      : kind === 'analytics' ? <AnalyticsWorkspace />
        : kind === 'program' ? <ProgramPreview aspectRatio="16 / 9" /> : <ProjectorView mode="direct" />);
  return { unmount: () => root.unmount() };
}
