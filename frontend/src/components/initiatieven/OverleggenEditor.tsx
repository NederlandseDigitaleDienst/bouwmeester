import { useEffect, useRef, useState } from 'react';

import { Input } from '@/components/common/Input';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, orUndef, useNlddEvent } from '@/components/nldd/events';
import { useUpdateInitiatiefSettings } from '@/hooks/useInitiatieven';
import type { InitiatiefDetail, Overleg } from '@/types';

import { opslaanFout } from './opslaanFout';

const MAX_OVERLEGGEN = 20;

/** Een id voor een nieuw overleg: kleine letters, cijfers en een liggend streepje. */
function nieuwId() {
  return `overleg_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

const schoon = (lijst: Overleg[]) =>
  lijst.map((o) => ({
    id: o.id,
    naam: o.naam.trim(),
    wanneer: o.wanneer?.trim() || null,
    wie: o.wie?.trim() || null,
    waarvoor: o.waarvoor?.trim() || null,
    vastgesteld: o.vastgesteld,
  }));
const gelijk = (a: Overleg[], b: Overleg[]) => JSON.stringify(schoon(a)) === JSON.stringify(schoon(b));

/**
 * Het ritme van het team beheren: de vaste overleggen, met per overleg wanneer,
 * met wie en waarvoor. De tab RegelRitme toont ze. Staat het moment nog niet
 * vast, dan haal je het vinkje weg en toont de tab het als open punt.
 *
 * Opslaan in één keer, net als de casusfunnel. Eigenaar-only, net als de
 * andere instellingen; de backend controleert dat ook.
 */
export function OverleggenEditor({ initiatief }: { initiatief: InitiatiefDetail }) {
  const settings = useUpdateInitiatiefSettings();
  const geldend = initiatief.overleggen ?? [];

  const [overleggen, setOverleggen] = useState<Overleg[]>(geldend);
  const [fout, setFout] = useState('');
  // Na opslaan of een herlaadactie de lijst van de server volgen.
  const geldendKey = JSON.stringify(geldend);
  useEffect(() => {
    setOverleggen(JSON.parse(geldendKey) as Overleg[]);
  }, [geldendKey]);

  const dirty = !gelijk(overleggen, geldend);
  const leegNaam = overleggen.some((o) => !o.naam.trim());

  const zet = (i: number, deel: Partial<Overleg>) =>
    setOverleggen((prev) => prev.map((o, j) => (j === i ? { ...o, ...deel } : o)));
  const verplaats = (i: number, richting: -1 | 1) =>
    setOverleggen((prev) => {
      const j = i + richting;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  const voegToe = () =>
    setOverleggen((prev) => [
      ...prev,
      { id: nieuwId(), naam: '', wanneer: null, wie: null, waarvoor: null, vastgesteld: true },
    ]);

  const opslaan = async () => {
    setFout('');
    try {
      await settings.mutateAsync({ id: initiatief.id, data: { overleggen: schoon(overleggen) } });
    } catch (e) {
      setFout(opslaanFout(e));
    }
  };

  return (
    <nldd-container gap="16">
      <nldd-text size="sm" color="secondary">
        De vaste overleggen van het team. De tab RegelRitme laat ze zien, zodat iedereen weet wanneer we elkaar
        zien en waarvoor. Is een overleg besloten maar het moment nog niet, haal dan het vinkje weg.
      </nldd-text>

      {overleggen.length === 0 && (
        <nldd-text size="sm" color="secondary">Nog geen overleggen vastgelegd.</nldd-text>
      )}

      {overleggen.map((o, i) => (
        <OverlegBlok
          key={o.id}
          overleg={o}
          nummer={i + 1}
          eerste={i === 0}
          laatste={i === overleggen.length - 1}
          onZet={(deel) => zet(i, deel)}
          onOmhoog={() => verplaats(i, -1)}
          onOmlaag={() => verplaats(i, 1)}
          onWeg={() => setOverleggen((prev) => prev.filter((_, j) => j !== i))}
        />
      ))}

      <div>
        <NlddButton
          variant="secondary"
          size="sm"
          startIcon="plus"
          onClick={voegToe}
          disabled={overleggen.length >= MAX_OVERLEGGEN}
          text="Overleg toevoegen"
        />
      </div>

      {fout && <nldd-text size="sm" color="critical">{fout}</nldd-text>}
      <nldd-container layout="row" gap="8" horizontal-alignment="right">
        <NlddButton variant="secondary" size="sm" disabled={!dirty} onClick={() => setOverleggen(geldend)} text="Herstellen" />
        <NlddButton size="sm" onClick={() => void opslaan()} loading={settings.isPending} disabled={!dirty || leegNaam} text="Opslaan" />
      </nldd-container>
    </nldd-container>
  );
}

interface OverlegProps {
  overleg: Overleg;
  nummer: number;
  eerste: boolean;
  laatste: boolean;
  onZet: (deel: Partial<Overleg>) => void;
  onOmhoog: () => void;
  onOmlaag: () => void;
  onWeg: () => void;
}

/** Eén overleg: naam en volgorde op een regel, daaronder wanneer, wie en waarvoor. */
function OverlegBlok({ overleg, nummer, eerste, laatste, onZet, onOmhoog, onOmlaag, onWeg }: OverlegProps) {
  return (
    <div style={{ border: '1px solid var(--primitives-color-neutral-200)', borderRadius: 'var(--semantics-surfaces-corner-radius)', padding: '12px' }}>
      <nldd-container gap="8">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-text size="sm" color="secondary" style={{ width: '20px', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
            {nummer}.
          </nldd-text>
          <nldd-container className="row-fill">
            <Input
              type="text"
              value={overleg.naam}
              aria-label={`Naam van overleg ${nummer}`}
              maxLength={80}
              placeholder="Naam van het overleg, bijvoorbeeld Demo"
              onChange={(e) => onZet({ naam: e.target.value })}
            />
          </nldd-container>
          <NlddIconButton icon="arrow-up" accessibleLabel={`Overleg ${nummer} omhoog`} variant="neutral-transparent" size="sm" disabled={eerste} onClick={onOmhoog} />
          <NlddIconButton icon="arrow-down" accessibleLabel={`Overleg ${nummer} omlaag`} variant="neutral-transparent" size="sm" disabled={laatste} onClick={onOmlaag} />
          <NlddIconButton icon="trash" accessibleLabel={`Overleg ${nummer} verwijderen`} variant="neutral-transparent" size="sm" onClick={onWeg} />
        </nldd-container>
        <nldd-form-field label="Wanneer">
          <Input
            type="text"
            value={overleg.wanneer ?? ''}
            maxLength={120}
            placeholder="Bijvoorbeeld: om de week, di 9.00 tot 11.00"
            onChange={(e) => onZet({ wanneer: e.target.value })}
          />
        </nldd-form-field>
        <nldd-form-field label="Wie">
          <Input
            type="text"
            value={overleg.wie ?? ''}
            maxLength={120}
            placeholder="Bijvoorbeeld: hele team, of de analisten"
            onChange={(e) => onZet({ wie: e.target.value })}
          />
        </nldd-form-field>
        <TekstVak
          label="Waarvoor"
          value={overleg.waarvoor ?? ''}
          placeholder="Wat doen we in dit overleg?"
          onChange={(waarvoor) => onZet({ waarvoor })}
        />
        <Vinkje
          label="Het moment staat vast"
          checked={overleg.vastgesteld}
          onChange={(vastgesteld) => onZet({ vastgesteld })}
        />
      </nldd-container>
    </div>
  );
}

/**
 * Een tekstvak van meer regels, als `nldd-multi-line-text-field`. De waarde
 * gaat via de property, zodat de cursor niet verspringt.
 */
function TekstVak({ label, value, placeholder, onChange }: { label: string; value: string; placeholder: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', (e) => onChange(eventValue(e)));
  useEffect(() => {
    const el = ref.current as (HTMLElement & { value?: string }) | null;
    if (el && el.value !== value) el.value = value;
  }, [value]);
  return (
    <nldd-form-field label={label}>
      <nldd-multi-line-text-field ref={ref} rows={2} width="full" placeholder={placeholder} maxlength={500} />
    </nldd-form-field>
  );
}

function Vinkje({ label, checked, onChange }: { label: string; checked: boolean; onChange: (aan: boolean) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', (e) => onChange(Boolean((e as CustomEvent<{ checked?: boolean }>).detail?.checked)));
  return <nldd-checkbox-field ref={ref} label={label} checked={orUndef(checked)} />;
}
