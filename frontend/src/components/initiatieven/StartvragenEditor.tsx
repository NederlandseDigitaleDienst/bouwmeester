import { useEffect, useRef, useState } from 'react';

import { Input } from '@/components/common/Input';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { CASUSTYPE_ID } from '@/components/casussen/startvragen';
import { useUpdateInitiatiefSettings } from '@/hooks/useInitiatieven';
import { ANTWOORDTYPE_LABELS, type Antwoordtype, type InitiatiefDetail, type Startvraag } from '@/types';
import { EisenLijst } from './EisenLijst';

const ANTWOORDTYPE_OPTIONS = Object.entries(ANTWOORDTYPE_LABELS).map(([value, label]) => ({ value, label }));
const MAX_VRAGEN = 30;

function isKeuze(t: Antwoordtype) {
  return t === 'een_keuze' || t === 'meer_keuzes';
}

/** Wat er nog niet klopt aan een vraag; leeg als hij goed is. Zelfde regels als de backend. */
function probleem(v: Startvraag): string {
  if (!v.vraag.trim()) return 'Vul de vraag in.';
  if (isKeuze(v.antwoordtype) && v.opties.filter((o) => o.trim()).length < 2) return 'Geef minstens twee keuzes.';
  return '';
}

/** Een id voor een nieuwe vraag: kleine letters, cijfers en een liggend streepje. */
function nieuwId() {
  return `vraag_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function Vinkje({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled?: boolean; onChange: (aan: boolean) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', (e) => onChange(Boolean((e as CustomEvent<{ checked?: boolean }>).detail?.checked)));
  return <nldd-checkbox-field ref={ref} label={label} checked={orUndef(checked)} disabled={orUndef(disabled)} />;
}

/**
 * De startvragen van een initiatief beheren: vragen toevoegen, aanpassen,
 * verplaatsen en weghalen. Per vraag het antwoordtype (ja/nee, één keuze,
 * meer keuzes, vrij antwoord), de keuzes, of hij verplicht is en of het
 * antwoord op het casuskaartje komt. De vraag naar intern of satelliet is
 * vast: hij bepaalt of de acceptatiecriteria volgen, dus alleen zijn plek en
 * "op het kaartje" zijn te veranderen. Opslaan stuurt de hele lijst; de
 * standaardlijst terugzetten stuurt een lege.
 */
export function StartvragenEditor({ initiatief }: { initiatief: InitiatiefDetail }) {
  const settingsMutation = useUpdateInitiatiefSettings();
  const geldend = initiatief.startvragen ?? [];
  const geldendKey = JSON.stringify(geldend);
  const [vragen, setVragen] = useState<Startvraag[]>(geldend);
  // Na opslaan of een herlaadactie de lijst van de server volgen.
  useEffect(() => {
    setVragen(JSON.parse(geldendKey) as Startvraag[]);
  }, [geldendKey]);

  const dirty = JSON.stringify(vragen) !== geldendKey;
  const geldig = vragen.every((v) => !probleem(v));

  const zet = (i: number, deel: Partial<Startvraag>) =>
    setVragen((lijst) =>
      lijst.map((v, j) => {
        if (j !== i) return v;
        const nieuw = { ...v, ...deel };
        // Geen keuzes bij ja/nee of een vrij antwoord; een vrij antwoord past niet op het kaartje.
        if (!isKeuze(nieuw.antwoordtype)) nieuw.opties = [];
        if (nieuw.antwoordtype === 'vrij') nieuw.op_kaartje = false;
        return nieuw;
      }),
    );
  const verplaats = (i: number, richting: -1 | 1) => {
    const j = i + richting;
    if (j < 0 || j >= vragen.length) return;
    const next = [...vragen];
    [next[i], next[j]] = [next[j], next[i]];
    setVragen(next);
  };
  const voegToe = () =>
    setVragen((lijst) => [
      ...lijst,
      { id: nieuwId(), vraag: '', antwoordtype: 'ja_nee', opties: [], verplicht: true, op_kaartje: false },
    ]);
  const opslaan = (lijst: Startvraag[]) =>
    settingsMutation.mutate({
      id: initiatief.id,
      data: { startvragen: lijst.map((v) => ({ ...v, vraag: v.vraag.trim(), opties: v.opties.map((o) => o.trim()).filter(Boolean) })) },
    });

  return (
    <nldd-container gap="12">
      {vragen.map((v, i) => {
        const vast = v.id === CASUSTYPE_ID;
        const fout = probleem(v);
        return (
          <div
            key={v.id}
            style={{
              border: '1px solid var(--primitives-color-neutral-200)',
              borderRadius: 'var(--semantics-surfaces-corner-radius)',
              padding: '12px',
            }}
          >
            <nldd-container gap="8">
              <nldd-container layout="row" gap="4" vertical-alignment="center">
                <nldd-text size="sm" color="secondary" style={{ width: '20px', fontVariantNumeric: 'tabular-nums' }}>
                  {i + 1}.
                </nldd-text>
                <nldd-container className="row-fill">
                  <Input
                    type="text"
                    value={v.vraag}
                    aria-label={`Vraag ${i + 1}`}
                    placeholder="Welke vraag stel je bij de start?"
                    maxLength={300}
                    disabled={vast}
                    onChange={(e) => zet(i, { vraag: e.target.value })}
                  />
                </nldd-container>
                <NlddIconButton icon="arrow-up" accessibleLabel={`Vraag ${i + 1} omhoog`} variant="neutral-transparent" size="sm" disabled={i === 0} onClick={() => verplaats(i, -1)} />
                <NlddIconButton icon="arrow-down" accessibleLabel={`Vraag ${i + 1} omlaag`} variant="neutral-transparent" size="sm" disabled={i === vragen.length - 1} onClick={() => verplaats(i, 1)} />
                {!vast && (
                  <NlddIconButton
                    icon="trash"
                    accessibleLabel={`Vraag ${i + 1} verwijderen`}
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => setVragen((lijst) => lijst.filter((_, j) => j !== i))}
                  />
                )}
              </nldd-container>
              <nldd-container layout="wrap" gap="16" vertical-alignment="center" style={{ paddingLeft: '24px' }}>
                <Select
                  size="sm"
                  width="200px"
                  aria-label={`Antwoordtype van vraag ${i + 1}`}
                  options={ANTWOORDTYPE_OPTIONS}
                  value={v.antwoordtype}
                  disabled={vast}
                  onChange={(e) => zet(i, { antwoordtype: e.target.value as Antwoordtype })}
                />
                <Vinkje label="Verplicht" checked={v.verplicht} disabled={vast} onChange={(verplicht) => zet(i, { verplicht })} />
                <Vinkje
                  label="Op het kaartje"
                  checked={v.op_kaartje}
                  disabled={v.antwoordtype === 'vrij'}
                  onChange={(op_kaartje) => zet(i, { op_kaartje })}
                />
              </nldd-container>
              {vast ? (
                <nldd-text size="xs" color="secondary" style={{ paddingLeft: '24px' }}>
                  Vaste vraag: hij bepaalt of de acceptatiecriteria volgen. Tekst en keuzes ({v.opties.join(' / ')}) liggen vast.
                </nldd-text>
              ) : (
                isKeuze(v.antwoordtype) && (
                  <div style={{ paddingLeft: '24px' }}>
                    <EisenLijst
                      items={v.opties}
                      onChange={(opties) => zet(i, { opties })}
                      naam="Keuze"
                      placeholder="Nieuwe keuze"
                      leeg="Nog geen keuzes. Voeg er minstens twee toe."
                      nieuwLabel={`Nieuwe keuze bij vraag ${i + 1}`}
                      max={20}
                    />
                  </div>
                )
              )}
              {fout && (
                <nldd-text size="xs" color="critical" style={{ paddingLeft: '24px' }}>
                  {fout}
                </nldd-text>
              )}
            </nldd-container>
          </div>
        );
      })}
      <div>
        <NlddButton variant="secondary" size="sm" startIcon="plus" onClick={voegToe} disabled={vragen.length >= MAX_VRAGEN} text="Vraag toevoegen" />
      </div>
      <nldd-container layout="row" gap="8" horizontal-alignment="right">
        <NlddButton variant="neutral-transparent" size="sm" onClick={() => opslaan([])} disabled={settingsMutation.isPending} text="Standaardlijst terugzetten" />
        <NlddButton variant="secondary" size="sm" disabled={!dirty} onClick={() => setVragen(geldend)} text="Herstellen" />
        <NlddButton size="sm" onClick={() => opslaan(vragen)} loading={settingsMutation.isPending} disabled={!dirty || !geldig} text="Opslaan" />
      </nldd-container>
    </nldd-container>
  );
}
