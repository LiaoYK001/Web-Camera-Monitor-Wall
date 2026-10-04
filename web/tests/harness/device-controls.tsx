// Development-only product UI fixture; API/microphone requests are supplied by tests.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import CameraRegistry from '../../src/CameraRegistry';
import '../../src/styles.css';

function Fixture() {
  const [open, setOpen] = useState(true);
  return <><button onClick={() => setOpen(value => !value)}>切换设备页面</button>
    {open && <CameraRegistry onBack={() => setOpen(false)} />}</>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
