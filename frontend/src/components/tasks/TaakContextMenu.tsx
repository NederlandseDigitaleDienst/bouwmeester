import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { Icon } from '@/components/nldd/Icon';

interface MenuProps {
  x: number;
  y: number;
  titel: string;
  onClose: () => void;
  onVerwijder: () => void;
}

/**
 * Het menu zelf: op de muispositie, binnen het scherm gehouden, in een portal
 * zodat een zijpaneel of een scrollende kolom het niet afsnijdt. Sluit bij
 * klikken ernaast, Escape, scrollen en een venster dat van grootte verandert.
 */
export function TaakContextMenu({ x, y, titel, onClose, onVerwijder }: MenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const knopRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const marge = 8;
    const { width, height } = el.getBoundingClientRect();
    setPos({
      left: Math.max(marge, Math.min(x, window.innerWidth - width - marge)),
      top: Math.max(marge, Math.min(y, window.innerHeight - height - marge)),
    });
    knopRef.current?.focus();
  }, [x, y]);

  useEffect(() => {
    const buiten = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const toets = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', buiten, true);
    document.addEventListener('contextmenu', buiten, true);
    document.addEventListener('keydown', toets);
    window.addEventListener('scroll', onClose, true);
    window.addEventListener('resize', onClose);
    return () => {
      document.removeEventListener('mousedown', buiten, true);
      document.removeEventListener('contextmenu', buiten, true);
      document.removeEventListener('keydown', toets);
      window.removeEventListener('scroll', onClose, true);
      window.removeEventListener('resize', onClose);
    };
  }, [onClose]);

  return createPortal(
    <div
      ref={ref}
      role="menu"
      aria-label={`Acties voor ${titel}`}
      style={{
        position: 'fixed',
        left: pos.left,
        top: pos.top,
        zIndex: 10000,
        minWidth: '180px',
        padding: '4px',
        background: 'var(--semantics-surfaces-base-background-color)',
        border: '1px solid var(--primitives-color-neutral-200)',
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.12)',
      }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <button
        ref={knopRef}
        type="button"
        role="menuitem"
        onClick={onVerwijder}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          width: '100%',
          padding: '6px 8px',
          border: 'none',
          borderRadius: 'var(--semantics-surfaces-corner-radius)',
          background: 'transparent',
          color: 'var(--semantics-content-critical-color)',
          font: 'inherit',
          fontSize: '14px',
          textAlign: 'left',
          cursor: 'pointer',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--primitives-color-neutral-100)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <Icon name="trash" size="sm" />
        Taak verwijderen
      </button>
    </div>,
    document.body,
  );
}
