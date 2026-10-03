import { useEffect } from 'react';

export function useDraftGuard(dirty: boolean, busy: boolean, message: string, onBusy: (notice: string) => void) {
  useEffect(() => {
    if (!dirty && !busy) return;
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    const navigate = (event: Event) => {
      if (busy) { event.preventDefault(); onBusy('正在保存，请稍候再切换页面'); }
      else if (!window.confirm(message)) event.preventDefault();
    };
    window.addEventListener('beforeunload', unload);
    window.addEventListener('webobs:before-navigate', navigate);
    return () => { window.removeEventListener('beforeunload', unload); window.removeEventListener('webobs:before-navigate', navigate); };
  }, [dirty, busy, message, onBusy]);
}
