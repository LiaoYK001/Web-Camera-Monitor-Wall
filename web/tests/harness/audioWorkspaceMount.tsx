import { createRoot } from 'react-dom/client';
import AudioWorkspace from '../../src/AudioWorkspace';
import type { StudioDocument } from '../../src/types';

export function mountAudioWorkspace(studio: StudioDocument, host: HTMLElement, options: { localPlayback?: boolean } = {}): { unmount: () => void; replace: (studio: StudioDocument) => void } {
  const root = createRoot(host);
  const render = (current: StudioDocument) => root.render(<AudioWorkspace studio={current} localPlayback={options.localPlayback} onCommitted={render} />);
  render(studio);
  return { unmount: () => root.unmount(), replace: render };
}
