import { useEffect, useState } from 'react';

import { Modal } from '@/components/common/Modal';
import { Select } from '@/components/common/Select';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { NlddButton } from '@/components/nldd/NlddButton';
import { Input } from '@/components/common/Input';
import { orUndef } from '@/components/nldd/events';
import { useInitiatief, useInitiatiefPersonen } from '@/hooks/useInitiatieven';
import { useStartCasus } from '@/hooks/useCasussen';
import { CASUSTYPE_ID, VASTE_VRAAG, antwoordTekst, isBeantwoord, type Waarde } from './startvragen';
import { CASUS_TYPE_LABELS } from '@/types';
import type { AcceptatieCriterium, CasusDetail, Lead, StartAntwoord, Startvoorwaarden, Startvraag } from '@/types';
import { CasusSoortenKiezer } from './CasusSoorten';
import { EisenNalopen, Vinkje } from './EisenNalopen';
import { heeftEisen, naarSoortEisen, sleutel, zetEis, type EisWaarden } from './eisen';
import { InstellingenBlok } from '@/components/initiatieven/InstellingenBlok';
import { useCasusSoorten } from '@/hooks/useCasusSoorten';

/**
 * Eén startvraag, naar zijn antwoordtype: ja/nee en één keuze als
 * keuzelijst, meer keuzes als vinkjes, een vrij antwoord als tekstveld. De
 * vaste vraag (intern of satelliet) bewaart 'intern' of 'satelliet', de
 * andere de tekst van de keuze zelf.
 */
function StartvraagVeld({
  vraag: v,
  waarde,
  onChange,
  zonderLabel = false,
}: {
  vraag: Startvraag;
  waarde: Waarde;
  onChange: (w: Waarde) => void;
  /** De vraag staat al in de kop van het blok: dan alleen als toegankelijke naam. */
  zonderLabel?: boolean;
}) {
  const label = zonderLabel ? undefined : v.vraag;
  const naam = zonderLabel ? { 'aria-label': v.vraag } : {};
  if (v.id === CASUSTYPE_ID) {
    return (
      <Select
        required
        label={label}
        {...naam}
        options={[{ value: '', label: 'Kies...' }, ...Object.entries(CASUS_TYPE_LABELS).map(([value, label]) => ({ value, label }))]}
        value={typeof waarde === 'string' ? waarde : ''}
        onChange={(e) => onChange(e.target.value || undefined)}
      />
    );
  }
  if (v.antwoordtype === 'meer_keuzes') {
    const gekozen = Array.isArray(waarde) ? waarde : [];
    const uitleg = v.verplicht ? 'Meer antwoorden kan, minstens één.' : 'Meer antwoorden kan.';
    const vinkjes = (
      <nldd-container gap="4" {...(zonderLabel ? { role: 'group', 'aria-label': v.vraag } : {})}>
        {v.opties.map((o) => (
          <Vinkje
            key={o}
            label={o}
            checked={gekozen.includes(o)}
            onChange={(aan) => onChange(aan ? [...gekozen, o] : gekozen.filter((x) => x !== o))}
          />
        ))}
      </nldd-container>
    );
    if (zonderLabel) {
      return (
        <nldd-container gap="8">
          <nldd-text size="xs" color="secondary">{uitleg}</nldd-text>
          {vinkjes}
        </nldd-container>
      );
    }
    return (
      <nldd-form-field label={v.vraag} supporting-label={uitleg} optional={orUndef(!v.verplicht)}>
        {vinkjes}
      </nldd-form-field>
    );
  }
  if (v.antwoordtype === 'vrij') {
    return (
      <Input
        label={label}
        {...naam}
        type="text"
        required={v.verplicht}
        value={typeof waarde === 'string' ? waarde : ''}
        onChange={(e) => onChange(e.target.value)}
        maxLength={5000}
      />
    );
  }
  const jaNee = v.antwoordtype === 'ja_nee';
  const opties = jaNee
    ? [{ value: 'ja', label: 'Ja' }, { value: 'nee', label: 'Nee' }]
    : v.opties.map((o) => ({ value: o, label: o }));
  const huidig = jaNee ? (waarde === true ? 'ja' : waarde === false ? 'nee' : '') : typeof waarde === 'string' ? waarde : '';
  return (
    <Select
      required={v.verplicht}
      label={label}
      {...naam}
      options={[{ value: '', label: 'Kies...' }, ...opties]}
      value={huidig}
      onChange={(e) => {
        const w = e.target.value;
        onChange(w === '' ? undefined : jaNee ? w === 'ja' : w);
      }}
    />
  );
}

/**
 * Wat er in de kop van het blok van een vraag staat: het antwoord, kort, of
 * dat hij nog open is (en verplicht).
 */
function antwoordSamenvatting(v: Startvraag, waarde: Waarde): string {
  if (!isBeantwoord(waarde)) return v.verplicht ? 'Nog niet beantwoord, verplicht' : 'Niet beantwoord';
  if (v.id === CASUSTYPE_ID && typeof waarde === 'string') {
    return CASUS_TYPE_LABELS[waarde as keyof typeof CASUS_TYPE_LABELS] ?? waarde;
  }
  if (Array.isArray(waarde)) return waarde.length === 1 ? waarde[0] : `${waarde.length} gekozen`;
  const tekst = antwoordTekst(waarde);
  return tekst.length > 40 ? `${tekst.slice(0, 40)}...` : tekst;
}

interface Props {
  /** De lead waaruit de casus start (vanuit het leaddetail). */
  lead: Lead | null;
  onClose: () => void;
  onStarted?: (casus: CasusDetail) => void;
  /**
   * Vanuit het casusbord: geen vaste lead, maar een keuze uit deze leads
   * (die in de startkolom staan en nog geen casus hebben). Het venster is
   * dan open zolang `open` waar is.
   */
  kiesUit?: Lead[];
  open?: boolean;
}

/**
 * Het startformulier: de startvragen van het initiatief en de trekker. De
 * vragen stelt het initiatief in (instellingen, Casus starten); zonder
 * initiatief alleen de vaste vraag. Trekker alleen uit wie het initiatief
 * kan zien, de backend bewaakt dat ook, net als de antwoorden.
 */
export function StartCasusModal({ lead: vasteLead, onClose, onStarted, kiesUit, open }: Props) {
  const start = useStartCasus();
  const [gekozenId, setGekozenId] = useState('');
  const kiezen = !vasteLead && !!kiesUit;
  const lead = vasteLead ?? kiesUit?.find((l) => l.id === gekozenId) ?? null;
  const isOpen = kiezen ? !!open : !!vasteLead;
  const initiatiefId = (lead ?? kiesUit?.[0])?.initiatief_id ?? undefined;
  const { data: personen = [] } = useInitiatiefPersonen(initiatiefId);
  // De acceptatiecriteria van het initiatief (instellingen); per criterium
  // afgevinkt of niet, met een uitleg.
  const { data: initiatief } = useInitiatief(initiatiefId);
  const criteriaLijst = initiatief?.acceptatiecriteria ?? [];
  const [criteria, setCriteria] = useState<Record<string, { akkoord: boolean; opmerking: string }>>({});
  const zetCriterium = (c: string, deel: Partial<{ akkoord: boolean; opmerking: string }>) =>
    setCriteria((prev) => {
      const huidig = prev[c] ?? { akkoord: false, opmerking: '' };
      return { ...prev, [c]: { ...huidig, ...deel } };
    });

  // De startvragen van het initiatief en de antwoorden, per vraag-id.
  const vragenGeladen = !initiatiefId || !!initiatief;
  const vragen: Startvraag[] = initiatiefId ? (initiatief?.startvragen ?? []) : [VASTE_VRAAG];
  const [waarden, setWaarden] = useState<Record<string, Waarde>>({});
  const satelliet = waarden[CASUSTYPE_ID] === 'satelliet';
  const [toelichting, setToelichting] = useState('');
  const [trekkerId, setTrekkerId] = useState('');
  // Casussoorten (tags) uit de instellingen van het initiatief.
  const { data: alleSoorten = [] } = useCasusSoorten(initiatiefId ?? null);
  const [soortIds, setSoortIds] = useState<string[]>([]);
  // De gekozen soorten in de volgorde van de instellingen, en hun starteisen:
  // per eis afgevinkt of niet, met een opmerking. Geen poort.
  const gekozenSoorten = alleSoorten.filter((s) => soortIds.includes(s.id));
  const [startEisen, setStartEisen] = useState<EisWaarden>({});

  // Een nieuwe vaste lead (vanuit het leaddetail): leeg formulier. Bij kiezen
  // uit een lijst niet, dan zou een keuze de antwoorden wissen; het casusbord
  // mount het venster per keer opnieuw.
  useEffect(() => {
    if (!vasteLead) return;
    setWaarden({});
    setToelichting('');
    setTrekkerId('');
    setCriteria({});
    setSoortIds([]);
    setStartEisen({});
  }, [vasteLead]);

  const personOptions: SelectOption[] = personen.map((p) => ({
    value: p.id,
    label: p.naam,
    description: p.functie ?? undefined,
  }));

  const compleet = !!lead && vragenGeladen && vragen.every((v) => !v.verplicht || isBeantwoord(waarden[v.id]));
  const leadOptions: SelectOption[] = [
    { value: '', label: 'Kies een lead' },
    ...(kiesUit ?? []).map((l) => ({ value: l.id, label: l.organization ? `${l.title} (${l.organization})` : l.title })),
  ];

  const submit = async () => {
    if (!lead || !compleet) return;
    const antwoorden: StartAntwoord[] = vragen
      .filter((v) => v.id !== CASUSTYPE_ID && isBeantwoord(waarden[v.id]))
      .map((v) => {
        const w = waarden[v.id];
        return {
          vraag_id: v.id,
          // Keuzes in de volgorde van de lijst, niet van het aanvinken.
          waarde: Array.isArray(w) ? v.opties.filter((o) => w.includes(o)) : typeof w === 'string' ? w.trim() : w,
        };
      });
    const startvoorwaarden: Startvoorwaarden = {
      casustype: waarden[CASUSTYPE_ID] as Startvoorwaarden['casustype'],
      antwoorden,
      toelichting: toelichting || null,
      // De acceptatiecriteria zijn de lijst voor satellietcasussen.
      ...(satelliet && criteriaLijst.length
        ? {
            acceptatiecriteria: criteriaLijst.map(
              (c): AcceptatieCriterium => ({
                criterium: c,
                akkoord: !!criteria[c]?.akkoord,
                opmerking: criteria[c]?.opmerking.trim() || null,
              }),
            ),
          }
        : {}),
      ...(heeftEisen(gekozenSoorten, 'start_eisen')
        ? { start_eisen: naarSoortEisen(gekozenSoorten, 'start_eisen', startEisen) }
        : {}),
    };
    try {
      const casus = await start.mutateAsync({
        lead_id: lead.id,
        startvoorwaarden,
        trekker_id: trekkerId || null,
        ...(soortIds.length ? { soort_ids: soortIds } : {}),
      });
      onClose();
      onStarted?.(casus);
    } catch {
      // toast is al getoond
    }
  };

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title={kiezen ? 'Nieuwe casus' : lead ? `Casus starten: ${lead.title}` : 'Casus starten'}
      size="md"
      closeable={!start.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" />
          <NlddButton onClick={submit} loading={start.isPending} disabled={!compleet} text="Casus starten" />
        </>
      }
    >
      <nldd-container gap="16">
        {/* Een casus begint altijd bij een lead: kies er een die klaarstaat. */}
        {kiezen && (kiesUit!.length > 0 ? (
          <Select required label="Uit welke lead?" options={leadOptions} value={gekozenId} onChange={(e) => setGekozenId(e.target.value)} />
        ) : (
          <nldd-text size="sm">
            Er staat nu geen lead klaar. Een casus begint bij een lead in de kolom In the pocket op de tab Leads,
            die nog geen casus heeft.
          </nldd-text>
        ))}
        <nldd-text size="sm" color="secondary">
          Het werk gaat daarna verder op de casus. De lead blijft in zijn kolom. De vragen stel je in
          bij de instellingen van het initiatief.
        </nldd-text>
        {!vragenGeladen ? (
          <nldd-text size="sm" color="secondary">Laden...</nldd-text>
        ) : (
          // Elke vraag een eigen blok om open en dicht te klappen, met het
          // antwoord in de kop: zo is het venster een overzicht. Een
          // verplichte vraag zonder antwoord begint open: zonder die vraag
          // blijft "Casus starten" uit, en dan moet je zien waarom.
          vragen.map((v) => (
            <InstellingenBlok
              key={v.id}
              icon={v.id === CASUSTYPE_ID ? 'check-mark-circle' : 'question-mark-circle'}
              titel={v.vraag}
              samenvatting={antwoordSamenvatting(v, waarden[v.id])}
              defaultOpen={v.verplicht && !isBeantwoord(waarden[v.id])}
            >
              <StartvraagVeld zonderLabel vraag={v} waarde={waarden[v.id]} onChange={(w) => setWaarden((a) => ({ ...a, [v.id]: w }))} />
            </InstellingenBlok>
          ))
        )}
        {/* De eisen klappen in, met de telling in de kop: het venster blijft
            kort, en je opent de lijst die je wilt nalopen. */}
        {satelliet && criteriaLijst.length > 0 && (
          <InstellingenBlok
            icon="check-list"
            titel="Acceptatiecriteria voor een satellietcasus"
            samenvatting={`${criteriaLijst.filter((c) => criteria[c]?.akkoord).length} van ${criteriaLijst.length} aangevinkt`}
          >
            <nldd-container gap="12">
              <nldd-text size="xs" color="secondary">Vink aan waaraan de casus voldoet, en licht toe waar dat helpt.</nldd-text>
              {criteriaLijst.map((c) => (
                <nldd-container key={c} gap="4">
                  <Vinkje label={c} checked={!!criteria[c]?.akkoord} onChange={(akkoord) => zetCriterium(c, { akkoord })} />
                  <Input
                    type="text"
                    value={criteria[c]?.opmerking ?? ''}
                    onChange={(e) => zetCriterium(c, { opmerking: e.target.value })}
                    aria-label={`Uitleg bij ${c}`}
                    placeholder="Uitleg of opmerking"
                    maxLength={2000}
                  />
                </nldd-container>
              ))}
            </nldd-container>
          </InstellingenBlok>
        )}
        {alleSoorten.length > 0 && (
          <InstellingenBlok
            icon="tag"
            titel="Soort casus"
            samenvatting={gekozenSoorten.length ? gekozenSoorten.map((s) => s.naam).join(', ') : 'Nog geen soort gekozen'}
          >
            <CasusSoortenKiezer soorten={alleSoorten} gekozen={soortIds} onChange={setSoortIds} />
          </InstellingenBlok>
        )}
        {heeftEisen(gekozenSoorten, 'start_eisen') && (
          <nldd-container gap="8">
            <nldd-container gap="2">
              <nldd-text size="sm" weight="bold">Voorwaarden om te starten van de gekozen soorten</nldd-text>
              <nldd-text size="xs" color="secondary">
                Vink aan wat klopt, en licht toe waar dat helpt. Starten kan ook als niet alles klopt.
              </nldd-text>
            </nldd-container>
            {/* Per soort een eigen blok om open te klappen. */}
            {gekozenSoorten
              .filter((soort) => (soort.start_eisen ?? []).length > 0)
              .map((soort) => {
                const eisen = soort.start_eisen ?? [];
                const af = eisen.filter((eis) => startEisen[sleutel(soort.id, eis)]?.akkoord).length;
                return (
                  <InstellingenBlok key={soort.id} icon="tag" titel={soort.naam} samenvatting={`${af} van ${eisen.length} aangevinkt`}>
                    <EisenNalopen
                      soorten={[soort]}
                      lijst="start_eisen"
                      waarden={startEisen}
                      onChange={(k, deel) => setStartEisen((w) => zetEis(w, k, deel))}
                    />
                  </InstellingenBlok>
                );
              })}
          </nldd-container>
        )}
        {/* Na de blokken de vrije velden. */}
        <RichTextFormField label="Toelichting" value={toelichting} onChange={setToelichting} rows={3} placeholder="Waarom deze keuzes?" />
        <CreatableSelect
          label="Trekker"
          value={trekkerId}
          onChange={setTrekkerId}
          options={personOptions}
          placeholder={lead?.initiatief_id ? 'Kies een trekker uit het initiatief...' : 'Kies een trekker...'}
          onClear={trekkerId ? () => setTrekkerId('') : undefined}
        />
      </nldd-container>
    </Modal>
  );
}
