import { createRoot } from 'react-dom/client';
import DeveloperDiagnostics from '../../src/DeveloperDiagnostics';
export function mountControlDiagnostics(host: HTMLElement) {
  const root = createRoot(host); root.render(<DeveloperDiagnostics />);
  return () => root.unmount();
}
