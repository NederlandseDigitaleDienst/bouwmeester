import { useRef } from 'react';

import { Input } from '@/components/common/Input';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import type { CasusSoortSummary, SoortEis } from '@/types';
import { sleutel, type EisWaarden, type Lijst } from './eisen';

/** Een vinkje met een label: een eis, een criterium of een antwoord. */
export function Vinkje({ label, checked, onChange }: { label: string; checked: boolean; onChange: (akkoord: boolean) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', (e) => onChange(Boolean((e as CustomEvent<{ checked?: boolean }>).detail?.checked)));
  return <nldd-checkbox-field ref={ref} label={label} checked={orUndef(checked)} />;
}

/**
 * De eisen van de soorten nalopen, bij de start of het afronden van een
 * casus: per soort zijn eisen, per eis een vinkje en een opmerking.
 */
export function EisenNalopen({
  soorten,
  lijst,
  waarden,
  onChange,
}: {
  soorten: CasusSoortSummary[];
  lijst: Lijst;
  waarden: EisWaarden;
  onChange: (sleutel: string, deel: Partial<{ akkoord: boolean; opmerking: string }>) => void;
}) {
  return (
    <nldd-container gap="16">
      {soorten
        .filter((s) => (s[lijst] ?? []).length > 0)
        .map((s) => (
          <nldd-container key={s.id} gap="8">
            <div>
              <nldd-tag text={s.naam} color={leadColumnTagColor(s.kleur)} size="sm" />
            </div>
            {(s[lijst] ?? []).map((eis) => {
              const k = sleutel(s.id, eis);
              return (
                <nldd-container key={eis} gap="4">
                  <Vinkje label={eis} checked={!!waarden[k]?.akkoord} onChange={(akkoord) => onChange(k, { akkoord })} />
                  <Input
                    type="text"
                    value={waarden[k]?.opmerking ?? ''}
                    onChange={(e) => onChange(k, { opmerking: e.target.value })}
                    aria-label={`Opmerking bij ${eis}`}
                    placeholder="Uitleg of opmerking"
                    maxLength={2000}
                  />
                </nldd-container>
              );
            })}
          </nldd-container>
        ))}
    </nldd-container>
  );
}

/** Een nagelopen lijst zoals hij bij de casus bewaard is: vinkje, eis, soort, opmerking. */
export function EisenMomentopname({ titel, eisen }: { titel: string; eisen: SoortEis[] }) {
  return (
    <nldd-container gap="6">
      <nldd-text size="xs" weight="medium" color="secondary">{titel}</nldd-text>
      {eisen.map((e) => (
        <div key={`${e.soort_id}-${e.eis}`} className="hug hug-top hug-gap-8">
          {e.akkoord ? (
            <nldd-icon icon="check-mark-circle" size="16" color="success" aria-hidden="true" />
          ) : (
            <nldd-icon icon="circle" size="16" aria-hidden="true" />
          )}
          <nldd-container gap="2">
            <nldd-text size="sm">
              {e.eis}
              <span className="visually-hidden">{e.akkoord ? ' (af)' : ' (niet af)'}</span>
            </nldd-text>
            <nldd-text size="xs" color="secondary">
              {e.soort}
              {e.opmerking ? `: ${e.opmerking}` : ''}
            </nldd-text>
          </nldd-container>
        </div>
      ))}
    </nldd-container>
  );
}
