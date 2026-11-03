import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { leadColumnTagColor } from '@/components/leads/stageColors';
import { Icon } from '@/components/nldd/Icon';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCasusSoorten } from '@/hooks/useCasusSoorten';
import type { CasusFaseDef, CasusSoort, InitiatiefDetail, Overleg } from '@/types';
import { initiatiefPath } from '@/utils/initiatiefRoutes';

const RAND = '1px solid var(--primitives-color-neutral-200)';

/**
 * De tab RegelRitme: hoe het team van dit initiatief werkt, op één pagina.
 * Het ritme (de vaste overleggen), hoe een casus instapt (de startvragen), de
 * reis door de fases van de RegelReis, wanneer iets af is (de DoD) en de
 * eisen per soort casus.
 *
 * Alles komt uit de inrichting van het initiatief; deze tab schrijft niets.
 * Wat de eigenaar bij Instellingen aanpast, staat hier dus meteen goed. Wie
 * mag aanpassen, krijgt per onderdeel een knop naar de instellingen.
 */
export function InitiatiefRegelRitme({ initiatief }: { initiatief: InitiatiefDetail }) {
  const navigate = useNavigate();
  const isEigenaar = initiatief.access_level === 'eigenaar';
  const { data: soorten } = useCasusSoorten(initiatief.id);

  const overleggen = initiatief.overleggen ?? [];
  const vragen = initiatief.startvragen ?? [];
  const fases = initiatief.casus_fases ?? [];
  const dod = initiatief.dod_items?.length ? initiatief.dod_items : (initiatief.dod_standaard ?? []);

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
          Hoe we werken: wanneer we elkaar zien, hoe een casus binnenkomt en welke reis hij aflegt op de RegelReis,
          tot er een besluit ligt. Deze pagina volgt de inrichting van het initiatief.
        </nldd-text>
        {initiatief.beschrijving && <RichTextDisplay content={initiatief.beschrijving} fallback="" />}
      </nldd-container>

      <Sectie icon="calendar" titel="Het ritme" actie={aanpassen}>
        {overleggen.length === 0 ? (
          <nldd-text size="sm" color="secondary">
            Nog geen overleggen vastgelegd.
            {isEigenaar ? ' Leg ze vast bij Instellingen, onder Ritme.' : ' De eigenaar van het initiatief legt ze vast.'}
          </nldd-text>
        ) : (
          overleggen.map((o) => <OverlegRegel key={o.id} overleg={o} />)
        )}
      </Sectie>

      <Sectie icon="signpost" titel="Instappen" actie={aanpassen}>
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

      <Sectie
        icon="flag"
        titel="De RegelReis"
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

      <Sectie icon="check-list" titel="Wanneer is een vraag af" actie={aanpassen}>
        <nldd-text size="sm">
          Een onderzoeksvraag is af als het team hem afrondt en deze punten naloopt, de definition of done.
        </nldd-text>
        <nldd-rich-text>
          <ul>
            {dod.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </nldd-rich-text>
      </Sectie>

      {!!soorten?.length && (
        <Sectie icon="check-mark-circle" titel="Soorten casus" actie={aanpassen}>
          <nldd-text size="sm">
            Bij de start en bij de stap naar de laatste fase loopt het team de eisen van de soort na, met een vinkje
            en een opmerking per eis. Dat is geen poort, wel een vast moment om stil te staan.
          </nldd-text>
          {soorten.map((s) => (
            <SoortRegel key={s.id} soort={s} />
          ))}
        </Sectie>
      )}

      <Sectie icon="users" titel="Wie doet wat">
        <nldd-rich-text>
          <ul>
            <li>
              <strong>Trekker:</strong> start de casus en jaagt hem aan. Aanjager, niet eigenaar van al het werk.
            </li>
            <li>
              <strong>Casusteam:</strong> een klein groepje per casus, alleen mensen uit het initiatief. Een
              onderzoeksvraag is van het team.
            </li>
            <li>
              <strong>Taak:</strong> het werk zelf, van één persoon, onder een onderzoeksvraag.
            </li>
          </ul>
        </nldd-rich-text>
      </Sectie>
    </nldd-container>
  );
}

/** Eén onderdeel van de pagina: kop met icoon en eventueel een knop, dan de inhoud. */
function Sectie({ icon, titel, actie, children }: { icon: string; titel: string; actie?: ReactNode; children: ReactNode }) {
  return (
    <section
      style={{
        border: RAND,
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
        background: 'var(--semantics-surfaces-base-background-color)',
        padding: '16px',
      }}
    >
      <nldd-container gap="12">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <Icon name={icon} size="sm" />
          <nldd-container className="row-fill">
            <nldd-title size={5}><h3>{titel}</h3></nldd-title>
          </nldd-container>
          {/* De knop houdt zijn breedte; de titel krijgt de rest. */}
          {actie && <div className="hug">{actie}</div>}
        </nldd-container>
        {children}
      </nldd-container>
    </section>
  );
}

/** Eén overleg: naam, en of het moment al vastligt; daaronder wanneer, wie en waarvoor. */
function OverlegRegel({ overleg }: { overleg: Overleg }) {
  return (
    <div style={{ borderTop: RAND, paddingTop: '12px' }}>
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

/** Een soort casus met hoe ver we hem brengen en zijn eisen bij start en eind. */
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
            <EisenLijst kop="Bij de start" eisen={soort.start_eisen ?? []} />
            <EisenLijst kop="Bij het einde" eisen={soort.eind_eisen ?? []} />
          </>
        ) : (
          <nldd-text size="sm" color="secondary">Nog geen eisen bij de start of het einde.</nldd-text>
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
        <nldd-text size="sm" color="secondary">Nog geen eisen.</nldd-text>
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
