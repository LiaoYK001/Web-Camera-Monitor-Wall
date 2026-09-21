import { createRoot } from 'react-dom/client';
import DirectPreview from '../../src/DirectPreview';
import type { SceneDocument } from '../../src/types';

export function mountWall(scene: SceneDocument, host: HTMLElement): { unmount: () => void } {
  const root = createRoot(host);
  root.render(<DirectPreview scene={scene} />);
  return { unmount: () => root.unmount() };
}
