import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import { Icon } from '@/components/nldd/Icon';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCasusSoorten } from '@/hooks/useCasusSoorten';
import { useLeadColumns } from '@/hooks/useLeadColumns';
import { CASUS_START_STAGE, type CasusFaseDef, type CasusSoort, type InitiatiefDetail, type Overleg } from '@/types';
import { initiatiefPath } from '@/utils/initiatiefRoutes';

import { InstellingenBlok } from './InstellingenBlok';

const RAND = '1px solid var(--primitives-color-neutral-200)';

/** "1 fase", "6 fases": een telling met het juiste woord. */
const tel = (n: number, een: string, meer: string) => `${n} ${n === 1 ? een : meer}`;

/**
 * De tab RegelRitme: hoe het team van dit initiatief werkt, op één pagina:
 * de weg van lead tot uitgewerkte casus en wie en wat daarin wat is,
 * dan het ritme (de vaste overleggen), hoe een casus instapt (de
 * startvragen), de reis door de fases van de RegelReis, wanneer iets af is
 * (de DoD) en de eisen per soort casus.
 *
 * De stappen en begrippen gelden voor elk initiatief: ze zeggen hoe
 * Bouwmeester werkt, met de namen (startkolom, fases) uit de inrichting.
 * De rest komt helemaal uit de inrichting; deze tab schrijft niets. Wat de
 * eigenaar bij Instellingen aanpast, staat hier dus meteen goed. Wie mag
 * aanpassen, krijgt per onderdeel een knop naar de instellingen.
 *
 * Elk onderdeel is een inklapbaar kaartje met een telling in de kop, zoals
 * op de tabs Mensen en Instellingen: dicht is de pagina een overzicht. De
 * weg van lead tot casus staat open, want daar begint de uitleg.
 */
export function InitiatiefRegelRitme({ initiatief }: { initiatief: InitiatiefDetail }) {
  const navigate = useNavigate();
  const isEigenaar = initiatief.access_level === 'eigenaar';
  const { data: soorten } = useCasusSoorten(initiatief.id);
  const { columns } = useLeadColumns(initiatief.id);

  const overleggen = initiatief.overleggen ?? [];
  const vragen = initiatief.startvragen ?? [];
  const fases = initiatief.casus_fases ?? [];
  const dod = initiatief.dod_items?.length ? initiatief.dod_items : (initiatief.dod_standaard ?? []);
  const startkolom = columns.find((c) => c.slug === CASUS_START_STAGE)?.name;
  const stappen = procesStappen(startkolom, fases);
  const nogOpen = overleggen.filter((o) => !o.vastgesteld).length;

  const aanpassen = isEigenaar ? (
    <NlddButton
      variant="neutral-transparent"
      size="sm"
      startIcon="pencil"
      text="Aanpassen"
      onClick={() => navigate(initiatiefPath(initiatief.id, 'instellingen'))}
    />
  ) : null;

  return (
    <nldd-container gap="24">
      <nldd-container gap="8">
        <nldd-title size={4}><h2>RegelRitme</h2></nldd-title>
        <nldd-text color="secondary">
          Hoe we werken: hoe een lead een uitgewerkte casus wordt, wie wat doet, wanneer we elkaar zien en welke
          reis een casus aflegt op de RegelReis. Deze pagina volgt de inrichting van het initiatief.
        </nldd-text>
        {initiatief.beschrijving && <RichTextDisplay content={initiatief.beschrijving} fallback="" />}
      </nldd-container>

      <nldd-container gap="12">
        <Sectie icon="users" titel="Wie en wat" samenvatting="van lead tot casusteam">
          <nldd-list dividers="never" accessible-label="Begrippen">
            {BEGRIPPEN.map((b) => (
              <nldd-list-item key={b.term}>
                <nldd-icon-cell icon={b.icon} vertical-alignment="top" />
                <nldd-spacer-cell size="8" />
                <nldd-title-cell text={b.term} supporting-text={b.uitleg} size={6} vertical-alignment="top" />
              </nldd-list-item>
            ))}
          </nldd-list>
        </Sectie>

        <Sectie icon="signpost" titel="Van lead tot uitgewerkte casus" samenvatting={tel(stappen.length, 'stap', 'stappen')} defaultOpen>
          <ProcesStappen stappen={stappen} />
        </Sectie>

        <Sectie
          icon="flag"
          titel="De RegelReis"
          samenvatting={tel(fases.length, 'fase', 'fases')}
          actie={
            <NlddButton
              variant="neutral-transparent"
              size="sm"
              endIcon="arrow-right"
              text="Naar de RegelReis"
              onClick={() => navigate(initiatiefPath(initiatief.id, 'casussen'))}
            />
          }
        >
          <nldd-text size="sm">
            Elke casus gaat deze fases door. Op de RegelReis zie je welke casus in welke fase staat.
          </nldd-text>
          {fases.map((f, i) => (
            <FaseRegel key={f.id} fase={f} nummer={i + 1} laatste={i === fases.length - 1} />
          ))}
        </Sectie>

        {!!soorten?.length && (
          <Sectie
            icon="check-mark-circle"
            titel="Soorten casus"
            samenvatting={tel(soorten.length, 'soort', 'soorten')}
            actie={aanpassen}
          >
            <nldd-text size="sm">
              Bij de start loopt het team de voorwaarden van de soort na, bij de stap naar de laatste fase de
              deliverables. Per punt een vinkje en een opmerking. Dat is geen poort, wel een vast moment om stil te
              staan.
            </nldd-text>
            {soorten.map((s) => (
              <SoortRegel key={s.id} soort={s} />
            ))}
          </Sectie>
        )}

        <Sectie icon="check-list" titel="Wanneer is een vraag beantwoord (DoD)" samenvatting={tel(dod.length, 'punt', 'punten')} actie={aanpassen}>
          <nldd-text size="sm">
            Of een onderzoeksvraag beantwoord is, beoordeel je met deze punten, de Definition of Done. Het team bepaalt ze samen. Ze zijn geen eindproduct of eisenlijst, maar de standaard voor wat af is. Het team loopt ze na als het de vraag afrondt.
          </nldd-text>
          <nldd-rich-text>
            <ul>
              {dod.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </nldd-rich-text>
        </Sectie>

        <Sectie
          icon="calendar"
          titel="Het ritme"
          samenvatting={
            overleggen.length
              ? `${tel(overleggen.length, 'overleg', 'overleggen')}${nogOpen ? ` · ${nogOpen} nog open` : ''}`
              : 'nog geen overleggen'
          }
          actie={aanpassen}
        >
          {overleggen.length === 0 ? (
            <nldd-text size="sm" color="secondary">
              Nog geen overleggen vastgelegd.
              {isEigenaar ? ' Leg ze vast bij Instellingen, onder Ritme.' : ' De eigenaar van het initiatief legt ze vast.'}
            </nldd-text>
          ) : (
            overleggen.map((o, i) => <OverlegRegel key={o.id} overleg={o} eerste={i === 0} />)
          )}
        </Sectie>

        <Sectie
          icon="signpost"
          titel="Instappen"
          samenvatting={vragen.length ? tel(vragen.length, 'startvraag', 'startvragen') : 'nog geen startvragen'}
          actie={aanpassen}
        >
          <nldd-text size="sm">
            Een aanvraag komt binnen als lead. Pakken we hem op, dan start de trekker vanuit de lead een casus en
            beantwoordt het team deze vragen. De antwoorden blijven bij de casus bewaard.
          </nldd-text>
          <nldd-rich-text>
            <ol>
              {vragen.map((v) => (
                <li key={v.id}>
                  {v.vraag}
                  {!v.verplicht && <span style={{ color: 'var(--semantics-content-secondary-color)' }}> (mag leeg)</span>}
                </li>
              ))}
            </ol>
          </nldd-rich-text>
        </Sectie>

      </nldd-container>
    </nldd-container>
  );
}

/**
 * Wie en wat: de begrippen van het casuswerk. Zo werkt Bouwmeester, dus voor
 * elk initiatief hetzelfde; de rechten volgen core/authority.py (een
 * casustaak wijzigen: bijdrager, eigenaar of trekker; de uitvoerder werkt
 * zijn eigen taak bij) en require_initiatief_member (wie een taak doet, ziet
 * het initiatief).
 */
const BEGRIPPEN: { icon: string; term: string; uitleg: string }[] = [
  {
    icon: 'inbox',
    term: 'Lead',
    uitleg:
      'Een aanvraag of kans die binnenkomt, voordat we iets toezeggen. Leads staan op de tab Leads en schuiven door de kolommen van de funnel. Niet elke lead wordt een casus.',
  },
  {
    icon: 'folder',
    term: 'Casus',
    uitleg:
      'Een organisatie heeft een casus, en die pakken we op. Een casus is dus niet hetzelfde als een lead: een organisatie kan meerdere casussen hebben. Een casus heeft een trekker, een casusteam, een of meer soorten en onderzoeksvragen, en gaat de fases van de RegelReis door.',
  },
  {
    icon: 'question-mark-circle',
    term: 'Onderzoeksvraag',
    uitleg:
      'De open vraag waar het casusteam samen aan werkt. Een vraag hangt onder een casus en is van het team, niet van één persoon. Of een onderzoeksvraag beantwoord is, beoordeel je met de Definition of Done.',
  },
  {
    icon: 'check-list',
    term: 'Definition of Done',
    uitleg:
      'De standaard waarmee het team beoordeelt of een onderzoeksvraag af is. Het is geen gewenst eindproduct en geen eisenlijst, maar een vaste maat die voor elke vraag geldt. Het team bepaalt de punten samen en loopt ze na bij het afronden van de vraag. Ze staan bij Wanneer is een vraag beantwoord (DoD), de eigenaar zet ze in de instellingen.',
  },
  {
    icon: 'check-mark-circle',
    term: 'Taak',
    uitleg:
      'Het werk zelf: duidelijk afgebakend, onder een onderzoeksvraag. Iedereen kan alle taken oppakken. Een open taak zet je dus niet op iemands naam. Dat doe je pas als iemand de taak gaat uitvoeren, en dan komt de naam van die persoon erop. Wie de taak doet, zet hem door van Open naar In uitvoering en Afgerond.',
  },
  {
    icon: 'flag',
    term: 'Trekker',
    uitleg:
      'Jaagt de casus aan. Aanjager, niet eigenaar van al het werk. De trekker wordt bij de start gekozen, mag de casus wijzigen, zoals de fase, en stelt het casusteam samen.',
  },
  {
    icon: 'users',
    term: 'Casusteam',
    uitleg:
      'De trekker en een klein groepje teamleden. Het team werkt samen aan de onderzoeksvragen. Binnen RegelRecht kunnen we ook kijkers uitnodigen, op het niveau van het initiatief of van de casus.',
  },
  {
    icon: 'hand',
    term: 'Kan iedereen een taak oppakken?',
    uitleg:
      'Ja. Het belangrijkste is dat op een taak de naam staat van wie hem uitvoert. Die naam zet je er zelf op, of iemand anders doet het. Iedereen die bijdrager of eigenaar is van het initiatief pakt taken op, ook bij een casus buiten het eigen casusteam. Ook kijkers kunnen een taak toegewezen krijgen en die dan zelf bijwerken.',
  },
];

/** "a", "a en b", "a, b en c". */
function opsomming(namen: string[]): string {
  if (namen.length <= 1) return namen[0] ?? '';
  return `${namen.slice(0, -1).join(', ')} en ${namen[namen.length - 1]}`;
}

/**
 * De weg van lead tot uitgewerkte casus. De startkolom en de fases komen uit
 * de inrichting; de rest is hoe Bouwmeester werkt.
 */
function procesStappen(startkolom: string | undefined, fases: CasusFaseDef[]): { titel: string; tekst: string }[] {
  const laatste = fases[fases.length - 1];
  return [
    {
      titel: 'Lead komt binnen',
      tekst: 'Een aanvraag of kans van buiten komt als lead op de tab Leads. Er is nog niets toegezegd.',
    },
    {
      titel: 'Leads Funnel',
      tekst: 'De lead schuift door de kolommen van de Leads Funnel. Zo bepalen we of er een casus in zit.',
    },
    {
      titel: 'Is er een casus?',
      tekst: `Een organisatie heeft een casus. Die verbinden we aan een casussoort en we besluiten of het een interne of externe casus is. Daaruit volgt een set voorwaarden om de casus te kunnen starten. Je start hem vanuit ${startkolom ? `de kolom ${startkolom}` : 'de startkolom'}, loopt de voorwaarden na en wijst de trekker aan.`,
    },
    {
      titel: 'Onderzoeksvragen stellen',
      tekst: 'De trekker en een klein casusteam uit het initiatief zetten de onderzoeksvragen onder de casus.',
    },
    {
      titel: 'Taken oppakken',
      tekst: 'Onder elke vraag komen de taken. Wie een taak oppakt, zet hem op eigen naam en houdt de status bij tot hij af is.',
    },
    {
      titel: 'Over de RegelReis',
      tekst: fases.length
        ? `De casus gaat de fases door: ${opsomming(fases.map((f) => f.naam))}. Of een onderzoeksvraag beantwoord is, beoordeel je met de Definition of Done.`
        : 'De casus gaat de fases van de RegelReis door. Of een onderzoeksvraag beantwoord is, beoordeel je met de Definition of Done.',
    },
    {
      titel: 'Uitgewerkt',
      // De vervolgcasus staat los achter de zin, zodat hij er ook staat als de
      // laatste fase geen "klaar als" heeft.
      tekst: `${
        laatste
          ? `Bij de stap naar ${laatste.naam} loopt het team de deliverables van de soort na.${laatste.door_als ? ` Klaar als ${laatste.door_als}` : ''}`
          : 'Bij de stap naar de laatste fase loopt het team de deliverables van de soort na.'
      } In deze stap kijken we ook of we een vervolgcasus kunnen starten met deze organisatie.`,
    },
  ];
}

/**
 * De stappen onder elkaar: een `nldd-list` met per rij een `nldd-step-cell`
 * (het genummerde bolletje op één doorlopende lijn) en een
 * `nldd-title-cell`, zoals het design system stappen onder elkaar
 * voorschrijft.
 */
function ProcesStappen({ stappen }: { stappen: { titel: string; tekst: string }[] }) {
  return (
    <nldd-list dividers="never" accessible-label="Van lead tot uitgewerkte casus">
      {stappen.map((s, i) => (
        <nldd-list-item key={s.titel}>
          <nldd-step-cell
            size="md"
            status="past"
            text={String(i + 1)}
            vertical-alignment="top"
            position={i === 0 ? 'first' : i === stappen.length - 1 ? 'last' : 'between'}
          />
          <nldd-spacer-cell size="8" />
          <nldd-title-cell text={s.titel} supporting-text={s.tekst} size={6} vertical-alignment="top" />
        </nldd-list-item>
      ))}
    </nldd-list>
  );
}

/**
 * Eén kaartje van de pagina, in te klappen: het blok van de tabs Mensen en
 * Instellingen, met de telling in de kop. De knop (Aanpassen, Naar de
 * RegelReis) staat onder de inhoud. In de kop zou hij in de uitklapknop
 * vallen, en op een smal scherm verdringt hij daar de titel.
 */
function Sectie({
  icon,
  titel,
  samenvatting,
  actie,
  defaultOpen,
  children,
}: {
  icon: string;
  titel: string;
  samenvatting?: string;
  actie?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <InstellingenBlok icon={icon} titel={titel} samenvatting={samenvatting} defaultOpen={defaultOpen}>
      <nldd-container gap="12">
        {children}
        {actie && <div className="hug">{actie}</div>}
      </nldd-container>
    </InstellingenBlok>
  );
}

/**
 * Eén overleg: naam, en of het moment al vastligt; daaronder wanneer, wie en
 * waarvoor. Het eerste overleg staat direct onder de kop van het kaartje,
 * die al een lijn heeft; daarom krijgt alleen de rest een lijn erboven.
 */
function OverlegRegel({ overleg, eerste }: { overleg: Overleg; eerste: boolean }) {
  return (
    <div style={eerste ? undefined : { borderTop: RAND, paddingTop: '12px' }}>
      <nldd-container gap="4">
        <nldd-container layout="wrap" gap="8" vertical-alignment="center">
          <nldd-text weight="medium">{overleg.naam}</nldd-text>
          {!overleg.vastgesteld && <nldd-tag text="Moment nog open" color="warning" size="sm" />}
        </nldd-container>
        {(overleg.wanneer || overleg.wie) && (
          <nldd-container layout="wrap" gap="16" vertical-alignment="center">
            {overleg.wanneer && (
              <div className="hug">
                <Icon name="clock" size="sm" />
                <nldd-text size="sm">{overleg.wanneer}</nldd-text>
              </div>
            )}
            {overleg.wie && (
              <div className="hug">
                <Icon name="users" size="sm" />
                <nldd-text size="sm">{overleg.wie}</nldd-text>
              </div>
            )}
          </nldd-container>
        )}
        {overleg.waarvoor && <nldd-text size="sm" color="secondary">{overleg.waarvoor}</nldd-text>}
      </nldd-container>
    </div>
  );
}

/** Eén fase van de RegelReis: nummer en naam in de kleur van het bord, wat er gebeurt, wanneer door. */
function FaseRegel({ fase, nummer, laatste }: { fase: CasusFaseDef; nummer: number; laatste: boolean }) {
  return (
    <div style={{ borderTop: RAND, paddingTop: '12px' }}>
      <nldd-container gap="4">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-text size="sm" color="secondary" style={{ width: '20px', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
            {nummer}.
          </nldd-text>
          <nldd-tag text={fase.naam} color={leadColumnTagColor(fase.kleur)} size="sm" />
        </nldd-container>
        {fase.omschrijving && <nldd-text size="sm">{fase.omschrijving}</nldd-text>}
        {fase.door_als && (
          <nldd-text size="sm" color="secondary">
            {laatste ? 'Klaar als' : 'Door als'} {fase.door_als}
          </nldd-text>
        )}
      </nldd-container>
    </div>
  );
}

/** Een soort casus met hoe ver we hem brengen, zijn voorwaarden om te starten en zijn deliverables. */
function SoortRegel({ soort }: { soort: CasusSoort }) {
  return (
    <div style={{ borderTop: RAND, paddingTop: '12px' }}>
      <nldd-container gap="4">
        <nldd-container layout="wrap" gap="8" vertical-alignment="center">
          <nldd-tag text={soort.naam} color={leadColumnTagColor(soort.kleur)} size="sm" />
          {soort.uitleg && <nldd-text size="sm" color="secondary">{soort.uitleg}</nldd-text>}
        </nldd-container>
        {soort.hoe_ver && <nldd-text size="sm">Hoe ver: {soort.hoe_ver}</nldd-text>}
        {soort.start_eisen?.length || soort.eind_eisen?.length ? (
          <>
            <EisenLijst kop="Voorwaarden om te starten" eisen={soort.start_eisen ?? []} />
            <EisenLijst kop="Deliverables" eisen={soort.eind_eisen ?? []} />
          </>
        ) : (
          <nldd-text size="sm" color="secondary">Nog geen voorwaarden of deliverables.</nldd-text>
        )}
      </nldd-container>
    </div>
  );
}

function EisenLijst({ kop, eisen }: { kop: string; eisen: string[] }) {
  return (
    <nldd-container gap="2">
      <nldd-text size="sm" weight="medium">{kop}</nldd-text>
      {eisen.length === 0 ? (
        <nldd-text size="sm" color="secondary">Nog niets ingevuld.</nldd-text>
      ) : (
        <nldd-rich-text>
          <ul>
            {eisen.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </nldd-rich-text>
      )}
    </nldd-container>
  );
}
