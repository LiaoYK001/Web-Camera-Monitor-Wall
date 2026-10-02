import { useLayoutEffect, useRef, type ReactNode } from 'react';

let scrollLocks = 0;
let originalOverflow: [string, string] = ['', ''];

/** Native dialogs trap keyboard focus and restore it to the opener on close. */
export default function Modal({ label, onClose, children, className = '' }: {
  label: string; onClose: () => void; children: ReactNode; className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const backdropPress = useRef(false);
  useLayoutEffect(() => {
    const dialog = ref.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    dialog?.querySelector<HTMLElement>('[data-modal-autofocus]')?.focus({ preventScroll: true });
    if (scrollLocks++ === 0) {
      originalOverflow = [document.documentElement.style.overflow, document.body.style.overflow];
      document.documentElement.style.overflow = document.body.style.overflow = 'hidden';
    }
    return () => {
      dialog?.close();
      if (--scrollLocks === 0) {
        [document.documentElement.style.overflow, document.body.style.overflow] = originalOverflow;
      }
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  const outside = (event: React.PointerEvent<HTMLDialogElement> | React.MouseEvent<HTMLDialogElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return event.target === event.currentTarget && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom);
  };
  return <dialog ref={ref} className={`app-modal ${className}`} aria-label={label}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onPointerDown={(event) => { backdropPress.current = outside(event); }}
    onClick={(event) => { if (backdropPress.current && outside(event)) onClose(); backdropPress.current = false; }}>
    {children}
  </dialog>;
}
