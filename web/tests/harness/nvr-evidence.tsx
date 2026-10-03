import { createRoot } from 'react-dom/client';
import { StrictMode } from 'react';
import NvrTimeline from '../../src/NvrTimeline';
import '../../src/styles.css';
createRoot(document.getElementById('root')!).render(<StrictMode><NvrTimeline onBack={() => {}} /></StrictMode>);
