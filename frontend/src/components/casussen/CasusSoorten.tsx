import { useEffect, useRef } from 'react';

import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import type { CasusSoort, CasusSoortSummary } from '@/types';

/** De soorten van een casus als gekleurde tags. Niets als er geen zijn. */
export function CasusSoortTags({ soorten }: { soorten?: CasusSoortSummary[] }) {
  if (!soorten || soorten.length === 0) return null;
  return (
    <>
      {soorten.map((s) => (
        // De uitleg als tooltip: wat betekent dit label ook alweer.
        <nldd-tag key={s.id} text={s.naam} color={leadColumnTagColor(s.kleur)} size="sm" {...(s.uitleg ? { title: s.uitleg } : {})} />
      ))}
    </>
  );
}

/**
 * Soorten kiezen: een vinkje per soort van het initiatief, met de uitleg
 * eronder als die er is, zodat je ziet wat je kiest. Zonder soorten in de
 * instellingen een verwijzing daarnaartoe.
 */
export function CasusSoortenKiezer({
  soorten,
  gekozen,
  onChange,
}: {
  soorten: CasusSoort[];
  gekozen: string[];
  onChange: (ids: string[]) => void;
}) {
  if (soorten.length === 0) {
    return (
      <nldd-text size="sm" color="secondary">
        Nog geen casussoorten. De eigenaar voegt ze toe bij de instellingen van het initiatief.
      </nldd-text>
    );
  }
  const zet = (id: string, aan: boolean) => {
    const set = new Set(gekozen);
    if (aan) set.add(id);
    else set.delete(id);
    // In de volgorde van de instellingen.
    onChange(soorten.map((s) => s.id).filter((sid) => set.has(sid)));
  };
  // Met uitleg onder elkaar, zodat de tekst leesbaar onder zijn vinkje staat;
  // zonder uitleg naast elkaar.
  const metUitleg = soorten.some((s) => s.uitleg);
  return (
    <nldd-container {...(metUitleg ? {} : { layout: 'wrap' as const })} gap={metUitleg ? '8' : '12'}>
      {soorten.map((s) => (
        <SoortVinkje key={s.id} soort={s} aan={gekozen.includes(s.id)} onChange={(aan) => zet(s.id, aan)} />
      ))}
    </nldd-container>
  );
}

/**
 * `nldd-checkbox-field` meldt een klik met een eigen `change`; vandaar de
 * ref. Het element stuurt die per klik twee keer, met dezelfde stand. Elke
 * melding is hier een opslagactie, dus de tweede wordt genegeerd: alleen een
 * stand die afwijkt van de laatst gemelde telt.
 */
function SoortVinkje({ soort, aan, onChange }: { soort: CasusSoort; aan: boolean; onChange: (aan: boolean) => void }) {
  const ref = useRef<HTMLElement>(null);
  const uitlegRef = useRef<HTMLElement>(null);
  const laatste = useRef(aan);
  // De uitleg als beschrijving van het vinkje voor schermlezers. Het
  // design system koppelt die via een elementverwijzing (describedByElements);
  // een id-verwijzing komt de shadow-DOM niet in.
  useEffect(() => {
    const el = ref.current as (HTMLElement & { describedByElements?: readonly Element[] }) | null;
    if (el) el.describedByElements = uitlegRef.current ? [uitlegRef.current] : [];
  }, [soort.uitleg]);
  useEffect(() => {
    laatste.current = aan;
  }, [aan]);
  useNlddEvent(ref, 'change', (e) => {
    const checked = (e as CustomEvent<{ checked?: boolean }>).detail?.checked;
    if (typeof checked !== 'boolean' || checked === laatste.current) return;
    laatste.current = checked;
    onChange(checked);
  });
  const vinkje = <nldd-checkbox-field ref={ref} label={soort.naam} checked={orUndef(aan)} />;
  if (!soort.uitleg) return vinkje;
  return (
    <nldd-container gap="2">
      {vinkje}
      {/* Ingesprongen tot onder het label, naast het vakje. */}
      <nldd-text ref={uitlegRef} size="xs" color="secondary" style={{ paddingLeft: '28px' }}>
        {soort.uitleg}
      </nldd-text>
    </nldd-container>
  );
}
