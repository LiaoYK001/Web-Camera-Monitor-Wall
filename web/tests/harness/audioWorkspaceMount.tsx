import { createRoot } from 'react-dom/client';
import AudioWorkspace from '../../src/AudioWorkspace';
import type { StudioDocument } from '../../src/types';

export function mountAudioWorkspace(studio: StudioDocument, host: HTMLElement): { unmount: () => void } {
  const root = createRoot(host);
  root.render(<AudioWorkspace studio={studio} onCommitted={() => undefined} />);
  return { unmount: () => root.unmount() };
}
