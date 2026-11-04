import { useEffect, useRef, useState } from 'react';

import { errorDetail } from '@/api/client';
import { Input } from '@/components/common/Input';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { TAG_KLEUR_OPTIES, leadColumnTagColor } from '@/components/leads/stageColors';
import { useUpdateInitiatiefSettings } from '@/hooks/useInitiatieven';
import type { CasusFaseDef, InitiatiefDetail } from '@/types';

const KLEUREN = TAG_KLEUR_OPTIES.map((k) => ({ value: k.value, label: k.label }));
const MAX_FASES = 12;

/** Een id voor een nieuwe fase, uit de naam: kleine letters, cijfers en _. */
function nieuweId(naam: string, bestaand: string[]): string {
  const basis =
    naam
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 34) || 'fase';
  let id = basis;
  for (let n = 2; bestaand.includes(id); n++) id = `${basis}_${n}`;
  return id;
}

const gelijk = (a: CasusFaseDef[], b: CasusFaseDef[]) => {
  const schoon = (l: CasusFaseDef[]) =>
    l.map((f) => ({
      id: f.id,
      naam: f.naam.trim(),
      kleur: f.kleur,
      omschrijving: f.omschrijving?.trim() || null,
      door_als: f.door_als?.trim() || null,
    }));
  return JSON.stringify(schoon(a)) === JSON.stringify(schoon(b));
};

/**
 * De casusfunnel bewerken: de fases waar een casus doorheen gaat, met per
 * fase een naam, kleur, omschrijving en wanneer een casus door mag ("door
 * als"; bij de laatste fase "klaar als"). Het funnelbord op de tab Casussen
 * neemt de fases over, en de casusgegevens tonen de omschrijving.
 *
 * Opslaan in één keer; zolang je niets eigens opslaat geldt het voorstel. Een
 * fase weghalen waar nog casussen in staan weigert de backend; die melding
 * staat dan onder de knoppen. Eigenaar-only, net als de andere instellingen.
 */
export function CasusFunnelEditor({ initiatief }: { initiatief: InitiatiefDetail }) {
  const settings = useUpdateInitiatiefSettings();
  const geldend = initiatief.casus_fases ?? [];
  const voorstel = initiatief.casus_fases_voorstel ?? [];
  const isVoorstel = initiatief.casus_fases_is_voorstel ?? true;

  const [fases, setFases] = useState<CasusFaseDef[]>(geldend);
  const [fout, setFout] = useState('');
  // Na opslaan of een herlaadactie de funnel van de server volgen.
  const geldendKey = JSON.stringify(geldend);
  useEffect(() => {
    setFases(JSON.parse(geldendKey) as CasusFaseDef[]);
  }, [geldendKey]);

  const dirty = !gelijk(fases, geldend);
  const leegNaam = fases.some((f) => !f.naam.trim());

  const zet = (i: number, deel: Partial<CasusFaseDef>) =>
    setFases((prev) => prev.map((f, j) => (j === i ? { ...f, ...deel } : f)));
  const verplaats = (i: number, richting: -1 | 1) =>
    setFases((prev) => {
      const j = i + richting;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  const voegToe = () =>
    setFases((prev) => [
      ...prev,
      { id: nieuweId(`fase ${prev.length + 1}`, prev.map((f) => f.id)), naam: '', kleur: 'neutral', omschrijving: null, door_als: null },
    ]);

  const bewaar = async (lijst: CasusFaseDef[]) => {
    setFout('');
    try {
      await settings.mutateAsync({ id: initiatief.id, data: { casus_fases: lijst } });
    } catch (e) {
      setFout(errorDetail(e) || 'Opslaan lukte niet.');
    }
  };
  const opslaan = () => {
    // Een nieuwe fase krijgt een id uit zijn naam; bestaande houden hun id.
    const ids: string[] = [];
    const lijst = fases.map((f) => {
      const id = geldend.some((g) => g.id === f.id) ? f.id : nieuweId(f.naam, [...ids, ...geldend.map((g) => g.id)]);
      ids.push(id);
      return { ...f, id, naam: f.naam.trim() };
    });
    // Gelijk aan het voorstel: niets eigens opslaan, dan volgt het initiatief het voorstel.
    void bewaar(gelijk(lijst, voorstel) ? [] : lijst);
  };

  return (
    <nldd-container gap="16">
      <nldd-text size="sm" color="secondary">
        De fases waar een casus doorheen gaat. Het funnelbord op de tab Casussen volgt deze lijst; bij een casus
        staat wat er in zijn fase gebeurt en wanneer hij door mag.
        {isVoorstel ? ' Dit is het voorstel; pas het aan en sla op om er een eigen funnel van te maken.' : ''}
      </nldd-text>

      {fases.map((f, i) => (
        <FaseBlok
          key={f.id}
          fase={f}
          nummer={i + 1}
          laatste={i === fases.length - 1}
          eerste={i === 0}
          enige={fases.length === 1}
          onZet={(deel) => zet(i, deel)}
          onOmhoog={() => verplaats(i, -1)}
          onOmlaag={() => verplaats(i, 1)}
          onWeg={() => setFases((prev) => prev.filter((_, j) => j !== i))}
        />
      ))}

      <div>
        <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={voegToe} disabled={fases.length >= MAX_FASES} text="Fase toevoegen" />
      </div>

      {fout && <nldd-text size="sm" color="critical">{fout}</nldd-text>}
      <nldd-container layout="row" gap="8" horizontal-alignment="right">
        {!isVoorstel && (
          <NlddButton variant="neutral-transparent" size="sm" onClick={() => void bewaar([])} disabled={settings.isPending} text="Terug naar het voorstel" />
        )}
        <NlddButton variant="secondary" size="sm" disabled={!dirty} onClick={() => setFases(geldend)} text="Herstellen" />
        <NlddButton size="sm" onClick={opslaan} loading={settings.isPending} disabled={!dirty || leegNaam} text="Opslaan" />
      </nldd-container>
    </nldd-container>
  );
}

interface FaseProps {
  fase: CasusFaseDef;
  nummer: number;
  eerste: boolean;
  laatste: boolean;
  enige: boolean;
  onZet: (deel: Partial<CasusFaseDef>) => void;
  onOmhoog: () => void;
  onOmlaag: () => void;
  onWeg: () => void;
}

/** Eén fase: naam, kleur en volgorde op een regel, daaronder de teksten. */
function FaseBlok({ fase, nummer, eerste, laatste, enige, onZet, onOmhoog, onOmlaag, onWeg }: FaseProps) {
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
              value={fase.naam}
              aria-label={`Naam van fase ${nummer}`}
              maxLength={60}
              placeholder="Naam van de fase"
              onChange={(e) => onZet({ naam: e.target.value })}
            />
          </nldd-container>
          <div style={{ width: '160px', flexShrink: 0 }}>
            <Select size="sm" aria-label={`Kleur van fase ${nummer}`} options={KLEUREN} value={fase.kleur} onChange={(e) => onZet({ kleur: e.target.value })} />
          </div>
          <div style={{ width: '120px', flexShrink: 0, overflow: 'hidden', whiteSpace: 'nowrap' }}>
            {fase.naam.trim() && <nldd-tag text={fase.naam} color={leadColumnTagColor(fase.kleur)} size="sm" />}
          </div>
          <NlddIconButton icon="arrow-up" accessibleLabel={`Fase ${nummer} omhoog`} variant="neutral-transparent" size="sm" disabled={eerste} onClick={onOmhoog} />
          <NlddIconButton icon="arrow-down" accessibleLabel={`Fase ${nummer} omlaag`} variant="neutral-transparent" size="sm" disabled={laatste} onClick={onOmlaag} />
          <NlddIconButton icon="trash" accessibleLabel={`Fase ${nummer} verwijderen`} variant="neutral-transparent" size="sm" disabled={enige} onClick={onWeg} />
        </nldd-container>
        <TekstVak
          label="Wat er gebeurt"
          value={fase.omschrijving ?? ''}
          placeholder="Wat gebeurt er in deze fase?"
          onChange={(omschrijving) => onZet({ omschrijving })}
        />
        <nldd-form-field label={laatste ? 'Klaar als' : 'Door als'}>
          <Input
            type="text"
            value={fase.door_als ?? ''}
            maxLength={500}
            placeholder={laatste ? 'Wanneer is de casus klaar?' : 'Wanneer mag de casus door naar de volgende fase?'}
            onChange={(e) => onZet({ door_als: e.target.value })}
          />
        </nldd-form-field>
      </nldd-container>
    </div>
  );
}

/**
 * Een tekstvak van meer regels, als `nldd-multi-line-text-field`. Het element
 * meldt typen met een eigen `input`; de waarde gaat via de property, zodat
 * de cursor niet verspringt.
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
      <nldd-multi-line-text-field ref={ref} rows={2} width="full" placeholder={placeholder} maxlength={1000} />
    </nldd-form-field>
  );
}
