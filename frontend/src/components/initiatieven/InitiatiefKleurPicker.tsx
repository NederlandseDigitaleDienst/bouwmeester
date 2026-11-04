import { useCallback, useRef } from 'react';
import { INITIATIEF_COLORS } from '@/types';
import { useNlddEvent, orUndef } from '@/components/nldd/events';
import { initiatiefIconColor } from './initiatiefColors';

/** Dutch names for the color options, so the choice is announced as a color
 *  rather than as a token. Only the names the picker offers. */
const KLEUR_LABELS: Record<(typeof INITIATIEF_COLORS)[number], string> = {
  lintblauw: 'Lintblauw',
  hemelblauw: 'Hemelblauw',
  groen: 'Groen',
  mosgroen: 'Mosgroen',
  geel: 'Geel',
  oranje: 'Oranje',
  rood: 'Rood',
  robijnrood: 'Robijnrood',
  paars: 'Paars',
  violet: 'Violet',
  roze: 'Roze',
  bruin: 'Bruin',
};

function KleurOption({
  kleur,
  selected,
  onSelect,
}: {
  kleur: (typeof INITIATIEF_COLORS)[number];
  selected: boolean;
  onSelect: (kleur: string) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(
    ref,
    'change',
    useCallback(() => onSelect(kleur), [onSelect, kleur]),
  );

  return (
    <nldd-toggle-button
      ref={ref}
      type="radio"
      variant="icon"
      size="md"
      value={kleur}
      selected={orUndef(selected)}
      accessible-label={KLEUR_LABELS[kleur]}
    >
      {/* The swatch is a filled circle in the color, which is what the option
          is about; the toggle button draws the chosen/unchosen state around it,
          so the choice does not rest on color alone. */}
      <nldd-icon slot="icon" icon="circle-filled" color={initiatiefIconColor(kleur)} />
    </nldd-toggle-button>
  );
}

/**
 * Pick an `Initiatief.kleur`.
 *
 * The value is an nldd color name, not a hex, so each option is a real radio
 * carrying that name rather than a bare button painted with a CSS color.
 */
export function InitiatiefKleurPicker({
  value,
  onChange,
}: {
  value: string | null | undefined;
  onChange: (kleur: string) => void;
}) {
  // No accessible-label here: every call site wraps this in an nldd-form-field,
  // which hands its own caption to the control and steps back from one that
  // names itself. Setting it would pre-empt that caption with a duplicate.
  return (
    <nldd-toggle-button-group type="radio" size="md">
      {INITIATIEF_COLORS.map((kleur) => (
        <KleurOption key={kleur} kleur={kleur} selected={value === kleur} onSelect={onChange} />
      ))}
    </nldd-toggle-button-group>
  );
}
