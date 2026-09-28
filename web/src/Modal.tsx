import { useLayoutEffect, useRef, type ReactNode } from 'react';

/** Native dialogs trap keyboard focus and restore it to the opener on close. */
export default function Modal({ label, onClose, children, className = '' }: {
  label: string; onClose: () => void; children: ReactNode; className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const dialog = ref.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    return () => { dialog?.close(); if (opener?.isConnected) opener.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={ref} className={`app-modal ${className}`} aria-label={label}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) {
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
    } }}>
    {children}
  </dialog>;
}
