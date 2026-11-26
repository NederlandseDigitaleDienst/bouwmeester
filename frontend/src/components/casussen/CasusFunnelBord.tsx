import { useMemo, useState } from 'react';

import { NlddButton } from '@/components/nldd/NlddButton';
import { useHaalUitKoelkast, useUpdateCasus } from '@/hooks/useCasussen';
import { useLeads } from '@/hooks/useLeads';
import { useInitiatief } from '@/hooks/useInitiatieven';
import { CASUS_START_STAGE } from '@/types';
import type { Casus, CasusDetail, CasusFaseDef } from '@/types';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import { CasusAfrondenModal } from './CasusAfrondenModal';
import { CasusCard } from './CasusCard';
import { heeftEisen } from './eisen';
import { KoelkastModal } from './KoelkastModal';
import { StartCasusModal } from './StartCasusModal';

/** De kolom van de koelkast: geen fase, de casus houdt zijn fase. */
const KOELKAST = '__koelkast__';

/** Wat een fase inhoudt, als tooltip op het label van de kolom. */
function faseUitleg(f: CasusFaseDef, laatste: boolean): string | undefined {
  const delen = [f.omschrijving, f.door_als ? `${laatste ? 'Klaar' : 'Door'} als: ${f.door_als}` : null].filter(Boolean);
  return delen.length ? delen.join('\n') : undefined;
}

interface Props {
  casussen: Casus[];
  initiatiefId: string;
  onOpen: (casusId: string) => void;
}

/**
 * Het casusbord, in dezelfde opmaak als het leadbord: per fase een getinte
 * baan met een gekleurd label en een teller, kaartjes erin, en onderaan
 * "Nieuwe casus". Een casus sleep je naar een andere fase.
 *
 * Een casus begint altijd bij een lead (zie de backend): "Nieuwe casus" laat
 * kiezen uit de leads die in de startkolom staan en nog geen casus hebben, en
 * vraagt dan de startvoorwaarden. De nieuwe casus komt in de kolom waar je op
 * "Nieuwe casus" klikte.
 *
 * De kolommen zijn de casusfunnel van het initiatief (instellingen): naam en
 * kleur per fase, en de omschrijving en "door als" als tooltip op het label.
 *
 * Rechts staat de koelkast: casussen die even stilliggen. Sleep je er een
 * heen, dan vraagt het bord waarom en wanneer hij er naar verwachting uit
 * komt. De casus houdt zijn fase; sleep je hem terug naar een kolom, dan
 * komt hij uit de koelkast in die fase.
 */
export function CasusFunnelBord({ casussen, initiatiefId, onOpen }: Props) {
  const updateCasus = useUpdateCasus();
  const uitKoelkast = useHaalUitKoelkast();
  // De casus waarvoor het koelkastvenster open is.
  const [naarKoelkast, setNaarKoelkast] = useState<Casus | null>(null);
  // De startvragen: welke antwoorden op de kaartjes komen.
  const { data: initiatief } = useInitiatief(initiatiefId);
  const vragen = initiatief?.startvragen ?? [];
  const fases = useMemo(() => initiatief?.casus_fases ?? [], [initiatief]);
  const [overKolom, setOverKolom] = useState<string | null>(null);
  const [gesleept, setGesleept] = useState<string | null>(null);
  // De fase waarvoor het startvenster open is; null is dicht.
  const [nieuwIn, setNieuwIn] = useState<string | null>(null);
  // De casus die naar de laatste fase gaat en eerst zijn eindeisen naloopt.
  const [afronden, setAfronden] = useState<Casus | null>(null);
  const laatste = fases.length ? fases[fases.length - 1] : undefined;

  const { data: startLeads = [] } = useLeads({ initiatief_id: initiatiefId, stage: CASUS_START_STAGE });
  const klaar = useMemo(() => startLeads.filter((l) => !l.casus_id), [startLeads]);

  const perFase = useMemo(() => {
    const map: Record<string, Casus[]> = Object.fromEntries(fases.map((f) => [f.id, [] as Casus[]]));
    map[KOELKAST] = [];
    for (const c of casussen) (map[c.koelkast_sinds ? KOELKAST : c.fase] ??= []).push(c);
    for (const lijst of Object.values(map)) lijst.sort((a, b) => a.title.localeCompare(b.title, 'nl'));
    return map;
  }, [casussen, fases]);

  // Naar de laatste fase met eindeisen: eerst nalopen, de fase gaat mee
  // met het afronden. Anders meteen. Uit de koelkast gaat in dezelfde
  // wijziging mee (ook in het afrondvenster), zodat de casus nooit uit de
  // koelkast is zonder zijn nieuwe fase.
  const zetFase = (casus: Casus, fase: string) => {
    if (fase === laatste?.id && heeftEisen(casus.soorten ?? [], 'eind_eisen')) setAfronden(casus);
    else updateCasus.mutate({ id: casus.id, data: { fase, ...(casus.koelkast_sinds ? { uit_koelkast: true } : {}) } });
  };

  const naarFase = (casusId: string, fase: string) => {
    const casus = casussen.find((c) => c.id === casusId);
    if (!casus) return;
    if (fase === KOELKAST) {
      if (!casus.koelkast_sinds) setNaarKoelkast(casus);
      return;
    }
    if (casus.fase === fase) {
      // Terug in zijn eigen fase: alleen uit de koelkast.
      if (casus.koelkast_sinds) uitKoelkast.mutate(casus.id);
      return;
    }
    // Naar een andere fase, ook vanuit de koelkast: één wijziging. Vraagt de
    // fase eerst het afrondvenster, dan blijft hij bij annuleren in de koelkast.
    zetFase(casus, fase);
  };
  const faseNaam = (id: string) => fases.find((f) => f.id === id)?.naam ?? id;
  const kolommen = [...fases.map((f, i) => ({ ...f, koelkast: false, laatsteFase: i === fases.length - 1 })), {
    id: KOELKAST,
    naam: 'Koelkast',
    kleur: 'hemelblauw',
    omschrijving: 'Casussen die even stilliggen, met waarom en wanneer ze er naar verwachting uit komen.',
    door_als: null,
    koelkast: true,
    laatsteFase: false,
  }];

  const gestart = (casus: CasusDetail) => {
    // Gestart in de eerste fase; klikte je in een andere kolom, dan daarheen.
    if (nieuwIn && casus.fase !== nieuwIn) zetFase(casus, nieuwIn);
  };

  return (
    <nldd-container gap="16">
      {/* Zelfde samenvatting als boven het leadbord: totaal en per fase. */}
      <nldd-container layout="wrap" gap="8" vertical-alignment="center">
        <nldd-text size="sm">{casussen.length} {casussen.length === 1 ? 'casus' : 'casussen'}</nldd-text>
        {kolommen.filter((f) => (perFase[f.id]?.length ?? 0) > 0).map((f) => (
          <nldd-tag key={f.id} text={`${f.naam}: ${perFase[f.id].length}`} color={leadColumnTagColor(f.kleur)} size="sm" />
        ))}
      </nldd-container>

      <div style={{ display: 'flex', gap: '12px', minHeight: '400px', overflowX: 'auto', paddingBottom: '8px' }}>
        {kolommen.map((f) => {
          const fase = f.id;
          const kaartjes = perFase[fase] ?? [];
          return (
            <div
              key={fase}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                setOverKolom(fase);
              }}
              onDragLeave={(e) => {
                const naar = e.relatedTarget as Node | null;
                if (naar && e.currentTarget.contains(naar)) return;
                setOverKolom(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                setOverKolom(null);
                setGesleept(null);
                const id = e.dataTransfer.getData('text/plain');
                if (id) naarFase(id, fase);
              }}
              style={{
                flex: '1 1 0',
                minWidth: '200px',
                width: '300px',
                borderRadius: 'var(--semantics-surfaces-corner-radius)',
                outline: overKolom === fase ? '2px solid var(--primitives-color-accent-300)' : 'none',
                outlineOffset: '-2px',
              }}
            >
              <nldd-box background="tinted">
                <nldd-container gap="0">
                  <nldd-container layout="row" gap="8" vertical-alignment="center" padding="12" padding-block="10">
                    <nldd-tag
                      text={f.naam}
                      color={leadColumnTagColor(f.kleur)}
                      size="sm"
                      {...(faseUitleg(f, f.laatsteFase) ? { title: faseUitleg(f, f.laatsteFase) } : {})}
                    />
                    <nldd-text size="xs" color="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {kaartjes.length}
                    </nldd-text>
                  </nldd-container>
                  <nldd-container gap="8" padding-inline="8" padding-bottom="8">
                    {kaartjes.length > 0 ? (
                      kaartjes.map((c) => (
                        <div
                          key={c.id}
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.setData('text/plain', c.id);
                            e.dataTransfer.effectAllowed = 'move';
                            setGesleept(c.id);
                          }}
                          onDragEnd={() => {
                            setGesleept(null);
                            setOverKolom(null);
                          }}
                          style={{ opacity: gesleept === c.id ? 0.4 : 1 }}
                        >
                          <CasusCard
                            casus={c}
                            onClick={() => onOpen(c.id)}
                            vragen={vragen}
                            {...(f.koelkast ? { faseNaam: faseNaam(c.fase) } : {})}
                          />
                        </div>
                      ))
                    ) : (
                      <nldd-container padding-block="24">
                        <nldd-text size="xs" color="secondary" horizontal-alignment="center">
                          {f.koelkast ? 'Sleep een casus hierheen die even stilligt' : 'Sleep casussen hierheen'}
                        </nldd-text>
                      </nldd-container>
                    )}
                  </nldd-container>
                  {!f.koelkast && <NlddButton
                    text="Nieuwe casus"
                    startIcon="plus"
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => setNieuwIn(fase)}
                    width="full"
                  />}
                </nldd-container>
              </nldd-box>
            </div>
          );
        })}
      </div>

      <StartCasusModal
        key={nieuwIn ?? 'dicht'}
        lead={null}
        kiesUit={klaar}
        open={!!nieuwIn}
        onClose={() => setNieuwIn(null)}
        onStarted={gestart}
      />
      <KoelkastModal casus={naarKoelkast} onClose={() => setNaarKoelkast(null)} />
      <CasusAfrondenModal casus={afronden} fase={afronden ? laatste ?? null : null} onClose={() => setAfronden(null)} />
    </nldd-container>
  );
}
