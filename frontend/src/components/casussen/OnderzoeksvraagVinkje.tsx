import { useRef } from 'react';

import { orUndef, useNlddEvent } from '@/components/nldd/events';

/**
 * Het vinkje "Dit is geen onderzoeksvraag". Onderzoeksvragen zijn leidend:
 * wat je aanmaakt is er een, tenzij je dit aanvinkt. `checked` betekent dus
 * "is een onderzoeksvraag", en het vinkje toont het omgekeerde. Eén plek,
 * zodat aanmaken in de backlog, aanmaken in de casus en het potloodje
 * hetzelfde vragen.
 *
 * `nldd-checkbox-field` meldt een klik met een eigen `change` (detail.checked);
 * een JSX-onChange op een custom element is geen echte listener, vandaar de
 * ref.
 */
export function OnderzoeksvraagVinkje({
  checked,
  onChange,
}: {
  /** Is het een onderzoeksvraag. */
  checked: boolean;
  /** Krijgt terug of het een onderzoeksvraag is, niet de stand van het vinkje. */
  onChange: (isVraag: boolean) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', (e) => onChange(!(e as CustomEvent<{ checked?: boolean }>).detail?.checked));
  return <nldd-checkbox-field ref={ref} label="Dit is geen onderzoeksvraag" checked={orUndef(!checked)} />;
}
