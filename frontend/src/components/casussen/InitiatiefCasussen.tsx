import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Select } from '@/components/common/Select';
import { ViewToggle, type ViewToggleOption } from '@/components/common/ViewToggle';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCasussen } from '@/hooks/useCasussen';
import { useLeads } from '@/hooks/useLeads';
import { CASUS_START_STAGE } from '@/types';
import { CasusFunnelBord } from './CasusFunnelBord';
import { CasusOverzicht } from './CasusOverzicht';
import { StartCasusModal } from './StartCasusModal';

type Weergave = 'funnel' | 'casus';
const WEERGAVEN: ViewToggleOption<Weergave>[] = [
  { value: 'funnel', label: 'Funnel', icon: 'columns-3' },
  { value: 'casus', label: 'Per casus', icon: 'list' },
];

/** Filterwaarde voor casussen zonder trekker; geen geldige naam. */
const ZONDER_EIGENAAR = '__zonder__';

/**
 * De tab Casussen, in twee weergaven met een schakelaar:
 *
 * - Funnel: een bord met de zes (dummy) fases uit het werkproces, in de
 *   opmaak van het leadbord (CasusFunnelBord). Een klik op een casus opent hem
 *   in de andere weergave; slepen zet hem in een andere fase; "Nieuwe casus"
 *   start er een uit een lead die klaarstaat.
 * - Per casus: kies een casus op naam, eventueel eerst gefilterd op
 *   casuseigenaar (de trekker). De casus staat dan inline, met zijn werk in
 *   hetzelfde formaat als de backlog. Geen venster: taakdetail en issue
 *   bewerken openen er al een.
 *
 * Weergave en casus staan in de URL (`?weergave=`, `?casus=`), zodat je een
 * casus kunt delen; de lead linkt zo ook naar zijn casus. Een casus ontstaat
 * altijd uit een lead: via "Casus starten" op die lead, of via "Nieuwe casus"
 * rechtsboven of in een kolom van het bord, die dezelfde regels volgen.
 */
export function InitiatiefCasussen({ initiatiefId }: { initiatiefId: string }) {
  const { data: casussen, isLoading } = useCasussen(initiatiefId);
  const [searchParams, setSearchParams] = useSearchParams();
  const [eigenaar, setEigenaar] = useState('');
  // Het startvenster van de knop rechtsboven; dezelfde leads als het bord.
  const [nieuw, setNieuw] = useState(false);
  // De plek in de kop voor de filters van het werk van de gekozen casus.
  const [filterPlek, setFilterPlek] = useState<HTMLElement | null>(null);
  const { data: startLeads = [] } = useLeads({ initiatief_id: initiatiefId, stage: CASUS_START_STAGE });
  const klaar = useMemo(() => startLeads.filter((l) => !l.casus_id), [startLeads]);

  const gekozen = searchParams.get('casus') ?? '';
  const gevraagd = searchParams.get('weergave');
  // Zonder keuze in de URL: met een casus erin per casus, anders de funnel.
  const weergave: Weergave = gevraagd === 'funnel' || gevraagd === 'casus' ? gevraagd : gekozen ? 'casus' : 'funnel';

  const zet = (volgende: { weergave?: Weergave; casus?: string }) => {
    const p = new URLSearchParams(searchParams);
    if (volgende.weergave) p.set('weergave', volgende.weergave);
    if (volgende.casus !== undefined) {
      if (volgende.casus) p.set('casus', volgende.casus);
      else p.delete('casus');
    }
    setSearchParams(p, { replace: true });
  };

  const lijst = useMemo(() => casussen ?? [], [casussen]);

  const eigenaarOptions = useMemo(() => {
    const namen = new Set<string>();
    let zonder = false;
    for (const c of lijst) {
      if (c.trekker_naam) namen.add(c.trekker_naam);
      else zonder = true;
    }
    return [
      { value: '', label: 'Iedereen' },
      ...[...namen].sort((a, b) => a.localeCompare(b, 'nl')).map((n) => ({ value: n, label: n })),
      ...(zonder ? [{ value: ZONDER_EIGENAAR, label: 'Zonder casuseigenaar' }] : []),
    ];
  }, [lijst]);

  const casusOptions = useMemo(() => {
    const passend = lijst
      .filter((c) => !eigenaar || (eigenaar === ZONDER_EIGENAAR ? !c.trekker_naam : c.trekker_naam === eigenaar))
      .sort((a, b) => a.title.localeCompare(b.title, 'nl'))
      .map((c) => ({ value: c.id, label: c.title }));
    // De gekozen casus blijft in de lijst, ook als het filter hem niet meer dekt.
    const huidige = lijst.find((c) => c.id === gekozen);
    if (huidige && !passend.some((o) => o.value === huidige.id)) passend.unshift({ value: huidige.id, label: huidige.title });
    return [{ value: '', label: passend.length ? 'Kies een casus' : 'Geen casussen' }, ...passend];
  }, [lijst, eigenaar, gekozen]);

  if (isLoading) return <LoadingSpinner padding="32" />;

  return (
    <nldd-container gap="12" padding="16">
      {/* Per casus links de keuzes, rechts in beide weergaven de schakelaar en
          Nieuwe casus, op een vaste plek (casus-kop in utilities.css): wisselen
          van weergave laat de knoppen staan waar ze stonden. */}
      <div className="casus-kop-houder">
        <div className="casus-kop">
          {weergave === 'casus' && (
            <div className="casus-kop-keuzes">
              <Select compact label="Casuseigenaar" size="sm" width="180px" options={eigenaarOptions} value={eigenaar} onChange={(e) => setEigenaar(e.target.value)} />
              <Select compact label="Casus" size="sm" width="280px" options={casusOptions} value={gekozen} onChange={(e) => zet({ casus: e.target.value })} />
              {/* Hier zet het werk van de gekozen casus zijn filters neer
                  (Status, Taakeigenaar), op dezelfde regel. */}
              <div ref={setFilterPlek} className="casus-kop-filters" />
            </div>
          )}
          <div className="casus-kop-acties">
            <ViewToggle
              value={weergave}
              onChange={(w) => zet({ weergave: w })}
              options={WEERGAVEN}
              variant="text"
              accessibleLabel="Weergave van de casussen"
            />
            {/* In beide weergaven: een casus starten uit een lead die klaarstaat.
                Hij begint in de eerste fase; per casus opent hij meteen. */}
            <NlddButton size="sm" startIcon="plus" onClick={() => setNieuw(true)} text="Nieuwe casus" />
          </div>
        </div>
      </div>

      {weergave === 'funnel' ? (
        <CasusFunnelBord casussen={lijst} initiatiefId={initiatiefId} onOpen={(id) => zet({ weergave: 'casus', casus: id })} />
      ) : (
        <nldd-container gap="12">
          {gekozen ? (
            <CasusOverzicht key={gekozen} casusId={gekozen} initiatiefId={initiatiefId} filterPlek={filterPlek} />
          ) : (
            <EmptyState
              title="Kies een casus"
              description={lijst.length ? 'Kies hierboven een casus op naam, of filter eerst op casuseigenaar.' : 'Dit initiatief heeft nog geen casussen.'}
            />
          )}
        </nldd-container>
      )}
      <StartCasusModal
        key={nieuw ? 'open' : 'dicht'}
        lead={null}
        kiesUit={klaar}
        open={nieuw}
        onClose={() => setNieuw(false)}
        onStarted={(casus) => {
          if (weergave === 'casus') zet({ casus: casus.id });
        }}
      />
    </nldd-container>
  );
}
