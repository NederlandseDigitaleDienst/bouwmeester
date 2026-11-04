import { useState } from 'react';

import { Input } from '@/components/common/Input';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';

interface Props {
  items: string[];
  onChange: (items: string[]) => void;
  /** Hoe één regel heet, voor de knoppen en schermlezers: "Eis", "Criterium". */
  naam: string;
  placeholder: string;
  /** Tekst bij een lege lijst. */
  leeg: string;
  /** Naam van het invoerveld onderaan, voor schermlezers: "Nieuwe eis". */
  nieuwLabel: string;
  max?: number;
}

/**
 * Een genummerde lijst korte regels om te bewerken: aanpassen, omhoog,
 * omlaag, weghalen, en onderaan een regel toevoegen (Enter of de knop).
 * Opslaan doet de aanroeper; dit onderdeel houdt alleen de lijst bij.
 * Gedeeld door de Definition of Done en de acceptatiecriteria.
 */
export function EisenLijst({ items, onChange, naam, placeholder, leeg, nieuwLabel, max = 30 }: Props) {
  const [nieuw, setNieuw] = useState('');

  const voegToe = () => {
    const t = nieuw.trim();
    if (!t || items.length >= max) return;
    onChange([...items, t]);
    setNieuw('');
  };
  const verplaats = (i: number, richting: -1 | 1) => {
    const j = i + richting;
    if (j < 0 || j >= items.length) return;
    const next = [...items];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };

  return (
    <nldd-container gap="12">
      {items.length === 0 ? (
        <nldd-text size="sm" color="secondary">{leeg}</nldd-text>
      ) : (
        <nldd-container gap="6">
          {items.map((item, i) => (
            <nldd-container key={i} layout="row" gap="4" vertical-alignment="center">
              <nldd-text size="sm" color="secondary" style={{ width: '20px', fontVariantNumeric: 'tabular-nums' }}>
                {i + 1}.
              </nldd-text>
              <nldd-container className="row-fill">
                <Input
                  type="text"
                  value={item}
                  aria-label={`${naam} ${i + 1}`}
                  maxLength={300}
                  onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))}
                />
              </nldd-container>
              <NlddIconButton
                icon="arrow-up"
                accessibleLabel={`${naam} ${i + 1} omhoog`}
                variant="neutral-transparent"
                size="sm"
                disabled={i === 0}
                onClick={() => verplaats(i, -1)}
              />
              <NlddIconButton
                icon="arrow-down"
                accessibleLabel={`${naam} ${i + 1} omlaag`}
                variant="neutral-transparent"
                size="sm"
                disabled={i === items.length - 1}
                onClick={() => verplaats(i, 1)}
              />
              <NlddIconButton
                icon="trash"
                accessibleLabel={`${naam} ${i + 1} verwijderen`}
                variant="neutral-transparent"
                size="sm"
                onClick={() => onChange(items.filter((_, j) => j !== i))}
              />
            </nldd-container>
          ))}
        </nldd-container>
      )}
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <nldd-container className="row-fill">
          <Input
            type="text"
            value={nieuw}
            aria-label={nieuwLabel}
            maxLength={300}
            placeholder={placeholder}
            onChange={(e) => setNieuw(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') voegToe();
            }}
          />
        </nldd-container>
        <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={voegToe} disabled={!nieuw.trim() || items.length >= max} text="Toevoegen" />
      </nldd-container>
    </nldd-container>
  );
}
