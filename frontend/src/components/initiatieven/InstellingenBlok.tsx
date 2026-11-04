import { useId, useState, type ReactNode } from 'react';

import { Icon } from '@/components/nldd/Icon';

interface Props {
  icon: string;
  titel: string;
  /** Een korte stand van zaken naast de titel, ook als het blok dicht is. */
  samenvatting?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

/**
 * Eén onderdeel van een initiatieftab, in te klappen (de instellingen en de
 * tab Mensen). Dicht zie je alleen de titel en de stand van zaken, zodat de
 * tab een overzicht blijft en je per onderdeel openklapt wat je nodig hebt.
 *
 * De kop is een echte knop in een `<h3>` (het patroon voor een
 * uitklapbare sectie): het toetsenbord en een schermlezer krijgen
 * `aria-expanded` en weten welk gebied erbij hoort. Het design system heeft
 * hier geen eigen component voor.
 */
export function InstellingenBlok({ icon, titel, samenvatting, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();

  return (
    <section
      style={{
        border: '1px solid var(--primitives-color-neutral-200)',
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
        background: 'var(--semantics-surfaces-base-background-color)',
      }}
    >
      <h3 style={{ margin: 0 }}>
        <button
          type="button"
          className="plain-button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((v) => !v)}
          style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', padding: '12px 16px', textAlign: 'left', cursor: 'pointer' }}
        >
          <Icon name={open ? 'chevron-down' : 'chevron-right'} size="sm" />
          <Icon name={icon} size="sm" />
          <nldd-text size="md" weight="medium">{titel}</nldd-text>
          {samenvatting && (
            <nldd-text size="sm" color="secondary" style={{ marginLeft: 'auto' }}>
              {samenvatting}
            </nldd-text>
          )}
        </button>
      </h3>
      {open && (
        <div id={id} style={{ padding: '4px 16px 16px', borderTop: '1px solid var(--primitives-color-neutral-200)' }}>
          <div style={{ paddingTop: '12px' }}>{children}</div>
        </div>
      )}
    </section>
  );
}
