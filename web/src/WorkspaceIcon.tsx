import type { ProductArea } from './WorkspaceShell';

const paths: Record<ProductArea | 'search' | 'more', string> = {
  monitor: 'M3 4h18v12H3z M8 20h8 M12 16v4',
  studio: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  devices: 'M3 6h13v12H3z M16 10l5-3v10l-5-3',
  audio: 'M5 4v16 M12 4v16 M19 4v16 M2 8h6 M9 15h6 M16 10h6',
  go2rtc: 'M4 7h14l-4-4 M20 17H6l4 4 M18 7l-4 4 M6 17l4-4',
  analytics: 'M4 3v17h17 M8 16v-5 M13 16V7 M18 16V4',
  events: 'M6 17V9a6 6 0 0 1 12 0v8l2 2H4z M10 22h4',
  archive: 'M4 4h16v16H4z M10 8l6 4-6 4z',
  storage: 'M4 4h16v6H4z M4 14h16v6H4z M16 7h1 M16 17h1',
  settings: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
  admin: 'M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M9 12l2 2 4-4',
  account: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 21v-2a8 8 0 0 1 16 0v2',
  search: 'M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0 M15 15l6 6',
  more: 'M4 5h16 M4 12h16 M4 19h16',
};

export default function WorkspaceIcon({ name }: { name: keyof typeof paths }) {
  return <svg className="workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
