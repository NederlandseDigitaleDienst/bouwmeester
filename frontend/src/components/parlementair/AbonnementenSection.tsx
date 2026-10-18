import { useCallback, useEffect, useRef, useState } from 'react';
import { Select } from '@/components/common/Select';
import { Icon } from '@/components/nldd/Icon';
import { eventValue, orUndef, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import {
  createAbonnement,
  deleteAbonnement,
  getAbonnementen,
  getGekoppeldeKanalen,
  suggereerZoektermen,
  suggestieFoutmelding,
  updateAbonnement,
  type GekoppeldKanaal,
  type ParlementairAbonnement,
  type Zoektermsuggestie,
} from '@/api/parlementairAbonnementen';

/**
 * Zoektermen die dit initiatief volgt in nieuwe kamerstukken.
 *
 * Het vangnet staat bewust breed (recall boven precisie), dus de telling
 * per term is het stuurmiddel: een term die niets oplevert is zichtbaar,
 * en een term die vaak wordt weggeklikt ook. Er wordt niets automatisch
 * uitgezet — een term die zichzelf deactiveert levert stil
 * dekkingsverlies op, en dat is erger dan ruis.
 */
export function AbonnementenSection({ initiatiefId }: { initiatiefId: string }) {
  const [abonnementen, setAbonnementen] = useState<ParlementairAbonnement[]>([]);
  const [nieuweTerm, setNieuweTerm] = useState('');
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);

  // Alleen het nieuwste verzoek mag de state schrijven. De modal wordt
  // hergebruikt tussen initiatieven, dus een traag antwoord van het vorige
  // initiatief kan anders over het nieuwe heen landen.
  const verzoekTeller = useRef(0);
  const gemonteerd = useRef(true);
  useEffect(() => {
    gemonteerd.current = true;
    return () => {
      gemonteerd.current = false;
    };
  }, []);

  const laden = useCallback(async () => {
    const mijnVerzoek = ++verzoekTeller.current;
    try {
      const data = await getAbonnementen(initiatiefId);
      if (gemonteerd.current && mijnVerzoek === verzoekTeller.current) {
        setAbonnementen(data);
      }
    } catch {
      if (gemonteerd.current && mijnVerzoek === verzoekTeller.current) {
        setFout('Kon de zoektermen niet ophalen.');
      }
    }
  }, [initiatiefId]);

  useEffect(() => {
    void laden();
  }, [laden]);

  // Waar de alerts landen. Zonder gekoppeld kanaal blijven ze in de
  // webapp, en dat hoort zichtbaar te zijn vóór iemand zoektermen instelt.
  useEffect(() => {
    let actueel = true;
    getGekoppeldeKanalen(initiatiefId)
      .then((k) => actueel && setKanalen(k))
      .catch(() => actueel && setKanalen([]));
    return () => {
      actueel = false;
    };
  }, [initiatiefId]);

  const toevoegen = useCallback(async () => {
    // Een tweede klik terwijl de eerste nog loopt levert een 409 op over
    // een term die je zojuist zelf toevoegde. De backend vangt de botsing
    // netjes af, maar de melding is dan onbegrijpelijk.
    if (bezig) return;
    const term = nieuweTerm.trim();
    if (term.length < 3) {
      setFout('Een zoekterm van minder dan drie tekens levert te veel ruis op.');
      return;
    }
    setBezig(true);
    setFout(null);
    try {
      await createAbonnement(initiatiefId, { term });
      setNieuweTerm('');
      await laden();
    } catch (e) {
      // 409 betekent: de term staat er al. Dat is geen fout van de
      // gebruiker maar informatie.
      const status = (e as { status?: number })?.status;
      setFout(
        status === 409
          ? 'Deze term wordt al gevolgd.'
          : 'Toevoegen is niet gelukt.',
      );
    } finally {
      setBezig(false);
    }
  }, [bezig, initiatiefId, laden, nieuweTerm]);

  // Welke rij een mutatie heeft lopen. Zonder dit vuurt een dubbelklik
  // twee PATCH-calls, en kunnen de antwoorden in omgekeerde volgorde
  // binnenkomen — dan staat de pil op het tegenovergestelde van wat de
  // server weet.
  const [bezigeRij, setBezigeRij] = useState<string | null>(null);
  const [kanalen, setKanalen] = useState<GekoppeldKanaal[] | null>(null);
  const [suggesties, setSuggesties] = useState<Zoektermsuggestie[] | null>(null);
  // Los van `fout`: een mislukte aanvraag mag niet als "niets gevonden"
  // op het scherm komen. En de reden verschilt — te vaak gevraagd, geen
  // taalmodel, bron onbereikbaar — wat bepaalt of de lezer moet wachten,
  // iets moet instellen of het later opnieuw moet proberen.
  const [suggestieFout, setSuggestieFout] = useState<string | null>(null);
  const [suggestiesBezig, setSuggestiesBezig] = useState(false);

  const haalSuggesties = useCallback(async () => {
    setSuggestiesBezig(true);
    setFout(null);
    setSuggestieFout(null);
    try {
      setSuggesties(await suggereerZoektermen(initiatiefId));
    } catch (e) {
      // De meting doet verzoeken aan een server van derden en een
      // LLM-call; als daar iets misgaat is dat geen reden om de rest van
      // het paneel onbruikbaar te maken.
      setSuggestieFout(suggestieFoutmelding(e));
      setSuggesties([]);
    } finally {
      setSuggestiesBezig(false);
    }
  }, [initiatiefId]);

  const voegSuggestieToe = useCallback(
    async (suggestie: Zoektermsuggestie) => {
      setFout(null);
      try {
        await createAbonnement(initiatiefId, { term: suggestie.term });
        setSuggesties((huidig) =>
          (huidig || []).filter((s) => s.term !== suggestie.term),
        );
        await laden();
      } catch {
        setFout(`Kon '${suggestie.term}' niet toevoegen.`);
      }
    },
    [initiatiefId, laden],
  );

  const schakel = useCallback(
    async (abonnement: ParlementairAbonnement) => {
      if (bezigeRij) return;
      setBezigeRij(abonnement.id);
      setFout(null);
      try {
        await updateAbonnement(initiatiefId, abonnement.id, {
          actief: !abonnement.actief,
        });
        await laden();
      } catch {
        setFout(`Kon '${abonnement.term}' niet aanpassen.`);
      } finally {
        setBezigeRij(null);
      }
    },
    [bezigeRij, initiatiefId, laden],
  );

  const zetDrempel = useCallback(
    async (abonnement: ParlementairAbonnement, waarde: number) => {
      if (bezigeRij) return;
      setBezigeRij(abonnement.id);
      setFout(null);
      try {
        await updateAbonnement(initiatiefId, abonnement.id, {
          minimum_relevantie: waarde,
        });
        await laden();
      } catch {
        setFout(`Kon de drempel van '${abonnement.term}' niet aanpassen.`);
      } finally {
        setBezigeRij(null);
      }
    },
    [bezigeRij, initiatiefId, laden],
  );

  const verwijder = useCallback(
    async (abonnement: ParlementairAbonnement) => {
      if (bezigeRij) return;
      setBezigeRij(abonnement.id);
      setFout(null);
      try {
        await deleteAbonnement(initiatiefId, abonnement.id);
        await laden();
      } catch {
        setFout(`Kon '${abonnement.term}' niet verwijderen.`);
      } finally {
        setBezigeRij(null);
      }
    },
    [bezigeRij, initiatiefId, laden],
  );

  return (
    <nldd-card>
      <nldd-container gap="12" padding="16">
        {/* Kop op dezelfde schaal als de andere kaarten op deze pagina.
            De knoppen staan hier en niet onder het veld: dit is waar je
            voor komt, en de uitleg hoort eronder, niet ertussen. */}
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-container width="fit-content" className="row-fill">
            <nldd-container layout="row" gap="6" vertical-alignment="center">
              <Icon name="search" size="sm" />
              <nldd-text size="xs" weight="bold" color="secondary">
                {abonnementen.length > 0
                  ? `Zoektermen (${abonnementen.length})`
                  : 'Zoektermen'}
              </nldd-text>
            </nldd-container>
          </nldd-container>
          {abonnementen.length > 0 && (
            <nldd-button
              variant="neutral-transparent"
              size="sm"
              text="Suggesties"
              start-icon="ai"
              loading={orUndef(suggestiesBezig)}
              onClick={haalSuggesties}
            />
          )}
        </nldd-container>

        {fout && <nldd-banner variant="critical" size="sm" text={fout} />}

        <nldd-container layout="row" gap="8" vertical-alignment="bottom">
          <TermField value={nieuweTerm} onChange={setNieuweTerm} onSubmit={toevoegen} />
          <nldd-button
            variant="secondary"
            size="sm"
            text="Volgen"
            start-icon="add"
            loading={orUndef(bezig)}
            onClick={toevoegen}
          />
        </nldd-container>

        {suggesties !== null && (
          <SuggestieLijst
            suggesties={suggesties}
            foutmelding={suggestieFout}
            onToevoegen={voegSuggestieToe}
            onSluiten={() => {
              setSuggesties(null);
              setSuggestieFout(null);
            }}
          />
        )}

        {abonnementen.length === 0 ? (
          <nldd-text size="xs" color="secondary">
            Nog geen zoektermen. Voeg er een toe, bijvoorbeeld de naam van dit
            initiatief zoals die in kamerstukken wordt geschreven.
          </nldd-text>
        ) : (
          <nldd-table
            columns="minmax(150px,2fr) 80px 100px 150px 110px 130px"
            sm-columns="1fr 70px 130px"
            md-columns="minmax(150px,2fr) 80px 100px 150px 130px"
            accessible-label="Gevolgde zoektermen"
          >
            <nldd-table-row slot="header">
              <nldd-text-cell text="Term" />
              <nldd-text-cell text="Treffers" horizontal-alignment="right" />
              <nldd-text-cell
                text="Weggeklikt"
                horizontal-alignment="right"
                hide-below="md"
              />
              <nldd-text-cell text="Drempel" hide-below="md" />
              <nldd-text-cell text="Laatste" hide-below="lg" />
              <nldd-text-cell />
            </nldd-table-row>
            {abonnementen.map((a) => (
              <AbonnementRow
                key={a.id}
                abonnement={a}
                bezig={bezigeRij === a.id}
                onToggle={() => schakel(a)}
                onDelete={() => verwijder(a)}
                onDrempel={(waarde) => zetDrempel(a, waarde)}
              />
            ))}
          </nldd-table>
        )}

        {/* Onder de tabel, want het legt uit wat je daar ziet. Eén alinea:
            vijf losse regels uitleg boven het invoerveld leest niemand. */}
        <nldd-text size="xs" color="secondary">
          Er wordt in de volledige tekst van nieuwe kamerstukken gezocht, ook in
          bijlagen en beslisnota&apos;s. Een term die niets oplevert is niet per
          se fout; een term die vaak wordt weggeklikt is waarschijnlijk te breed.
        </nldd-text>

        <Bezorging kanalen={kanalen} />
      </nldd-container>
    </nldd-card>
  );
}

/**
 * Waar de alerts van dit initiatief naartoe gaan.
 *
 * Dit stond eerst als belofte in de inleiding ("verschijnen in de
 * gekoppelde Mattermost-kanalen"), maar die kanalen kunnen er niet zijn.
 * Dan landen de treffers alleen in de webapp, en dat is iets anders dan
 * wat de tekst suggereerde.
 */
function Bezorging({ kanalen }: { kanalen: GekoppeldKanaal[] | null }) {
  if (kanalen === null) return null;

  if (kanalen.length === 0) {
    return (
      <nldd-banner
        variant="warning"
        size="sm"
        text="Dit initiatief heeft geen gekoppeld Mattermost-kanaal"
        supporting-text={
          'Treffers worden wel bewaard en zijn hier zichtbaar, maar er gaat ' +
          'geen bericht uit. Koppel een kanaal met /bouwmeester koppel ' +
          'initiatief <naam>.'
        }
      />
    );
  }

  const namen = kanalen
    .map((k) => `~${k.channel_name}`)
    .join(', ');
  return (
    <nldd-text size="xs" color="secondary">
      Berichten gaan naar {kanalen.length === 1 ? 'kanaal' : 'de kanalen'} {namen}.
    </nldd-text>
  );
}

/**
 * Voorgestelde zoektermen, met wat ze bij de bron opleveren.
 *
 * Het getal dat telt is `nieuwe_treffers`: een term die alleen dubbelt met
 * wat je al volgt voegt niets toe, hoeveel treffers hij ook heeft. Bij een
 * meting leverden vijf van de zes voorgestelde termen nul stukken op, dus
 * zonder deze getallen zou je vooral ruis aanzetten.
 */
function SuggestieLijst({
  suggesties,
  foutmelding,
  onToevoegen,
  onSluiten,
}: {
  suggesties: Zoektermsuggestie[];
  foutmelding: string | null;
  onToevoegen: (s: Zoektermsuggestie) => void;
  onSluiten: () => void;
}) {
  if (suggesties.length === 0) {
    // De knop staat onder de banner, niet ernaast: een `nldd-banner` in
    // een rij-container neemt de volle breedte en duwt een buurelement
    // buiten de modal. Verticaal stapelen houdt beide binnen beeld, ook
    // op telefoonbreedte.
    //
    // Geen `dismissible` op de banner zelf: die knop dispatcht alleen een
    // event en verwacht dat de consument de banner verbergt. Zonder
    // handler blijft hij staan en lijkt de X stuk.
    return (
      <nldd-container gap="8">
        <nldd-banner
          variant={foutmelding ? 'warning' : 'neutral'}
          size="sm"
          text={foutmelding ?? 'Geen aanvullende zoektermen gevonden.'}
          supporting-text={
            foutmelding
              ? undefined
              : 'Het model vond geen varianten die iets toevoegen aan wat je al volgt.'
          }
        />
        <div className="hug hug-stack">
          <nldd-button
            variant="neutral-transparent"
            size="xs"
            text="Sluiten"
            onClick={onSluiten}
          />
        </div>
      </nldd-container>
    );
  }

  return (
    <nldd-card>
      <nldd-container gap="8" padding="16">
        <nldd-container
          layout="row"
          gap="8"
          vertical-alignment="center"
          width="full"
          min-width="0"
        >
          {/* De tekst vult de rij, zodat de knop erachter rechts komt.
              `space-between` bestaat niet op nldd-container: die kent
              alleen left|center|right, en een onbekende waarde faalt
              stil omdat het type te ruim is om hem te vangen. */}
          <nldd-container width="full" min-width="0">
            <nldd-text size="xs" weight="bold">
              Voorgestelde zoektermen
            </nldd-text>
          </nldd-container>
          {/* Geen `width="fit-content"`-wrapper: die klapt dicht zonder
              min-width (zie de nldd-markup-hook). De knop bepaalt zijn
              eigen breedte en de ouder duwt hem naar rechts. */}
          <nldd-button
            variant="neutral-transparent"
            size="xs"
            text="Sluiten"
            onClick={onSluiten}
          />
        </nldd-container>
        <nldd-text size="xs" color="secondary">
          De aantallen zijn gemeten bij de bron. &quot;Nieuw&quot; telt alleen
          stukken die je huidige termen nog niet vinden; een term zonder
          nieuwe treffers kan alsnog nuttig zijn als je een van je andere
          termen later weghaalt.
        </nldd-text>
        {suggesties.map((s) => (
          <nldd-container key={s.term} layout="row" gap="8" vertical-alignment="center">
            <nldd-container gap="2">
              <nldd-container layout="row" gap="6" vertical-alignment="center">
                <nldd-text size="xs" weight="bold">
                  {s.term}
                </nldd-text>
                <nldd-text size="xs" color="secondary">
                  {s.treffers === 1 ? '1 treffer' : `${s.treffers} treffers`}
                </nldd-text>
                {s.nieuwe_treffers > 0 ? (
                  <nldd-tag
                    size="sm"
                    color="groen"
                    text={`${s.nieuwe_treffers} nieuw`}
                  />
                ) : (
                  <nldd-text size="xs" color="secondary">
                    · geen nieuwe
                  </nldd-text>
                )}
              </nldd-container>
              <nldd-text size="xs" color="secondary">
                {s.reden}
              </nldd-text>
            </nldd-container>
            <nldd-button
              variant="secondary"
              size="xs"
              text="Volgen"
              accessible-label={`Volg ${s.term}`}
              onClick={() => onToevoegen(s)}
            />
          </nldd-container>
        ))}
      </nldd-container>
    </nldd-card>
  );
}

/** Een controlled `nldd-text-field` voor een nieuwe zoekterm. */
function TermField({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddValue(ref, value);
  useNlddEvent(
    ref,
    'input',
    useCallback((e: Event) => onChange(eventValue(e)), [onChange]),
  );
  useNlddEvent(
    ref,
    'keydown',
    useCallback(
      (e: Event) => {
        if ((e as KeyboardEvent).key === 'Enter') {
          e.preventDefault();
          onSubmit();
        }
      },
      [onSubmit],
    ),
  );
  return (
    <nldd-text-field
      ref={ref}
      placeholder="Bijvoorbeeld: Nederlandse Digitale Dienst"
      accessible-label="Nieuwe zoekterm"
    />
  );
}

function AbonnementRow({
  abonnement,
  bezig,
  onToggle,
  onDelete,
  onDrempel,
}: {
  abonnement: ParlementairAbonnement;
  bezig: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onDrempel: (waarde: number) => void;
}) {
  const laatste = abonnement.laatste_treffer_op
    ? new Date(abonnement.laatste_treffer_op).toLocaleDateString('nl-NL')
    : '—';

  return (
    <nldd-table-row>
      <nldd-cell>
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          <nldd-text size="xs" color={abonnement.actief ? undefined : 'secondary'}>
            {abonnement.term}
          </nldd-text>
          {!abonnement.actief && <nldd-tag size="sm" color="neutral" text="uit" />}
        </nldd-container>
      </nldd-cell>
      <nldd-text-cell
        text={String(abonnement.treffers)}
        horizontal-alignment="right"
      />
      <nldd-text-cell
        text={String(abonnement.weggeklikt_totaal)}
        horizontal-alignment="right"
        hide-below="md"
      />
      <nldd-cell hide-below="md">
        <DrempelKeuze
          waarde={abonnement.minimum_relevantie}
          bezig={bezig}
          term={abonnement.term}
          onKies={onDrempel}
        />
      </nldd-cell>
      <nldd-text-cell text={laatste} hide-below="lg" />
      <nldd-cell>
        <nldd-container layout="row" gap="4" horizontal-alignment="right">
          <nldd-button
            variant="neutral-transparent"
            size="xs"
            text={abonnement.actief ? 'Pauzeer' : 'Hervat'}
            disabled={orUndef(bezig)}
            accessible-label={
              abonnement.actief
                ? `Pauzeer ${abonnement.term}`
                : `Hervat ${abonnement.term}`
            }
            onClick={onToggle}
          />
          <nldd-button
            variant="critical-transparent"
            size="xs"
            start-icon="delete"
            disabled={orUndef(bezig)}
            accessible-label={`Verwijder ${abonnement.term}`}
            onClick={onDelete}
          />
        </nldd-container>
      </nldd-cell>
    </nldd-table-row>
  );
}

/**
 * Hoe streng een term filtert, in woorden in plaats van in een getal.
 *
 * De schaal is 0-100 en niemand kan daar een zinnig getal bij bedenken.
 * Drie keuzes dekken wat er in de praktijk nodig is: een smalle term wil
 * je ongefilterd, een brede term als "Fundament" (90 treffers) juist niet.
 *
 * De waarden komen uit een meting over 146 beoordeelde stukken: twintig
 * stukken scoorden tussen 10 en 19 en geen van alle ging over de NLDD,
 * en het echte werk begint pas bij 40.
 */
const DREMPELS = [
  { waarde: 0, label: 'Alles tonen' },
  { waarde: 20, label: 'Normaal' },
  { waarde: 40, label: 'Alleen relevante' },
] as const;

function DrempelKeuze({
  waarde,
  bezig,
  term,
  onKies,
}: {
  waarde: number;
  bezig: boolean;
  term: string;
  onKies: (waarde: number) => void;
}) {
  // `Select` en niet een kale `nldd-dropdown`: de dropdown roept
  // `stopPropagation()` aan op het native change-event en stuurt een eigen
  // CustomEvent, die React niet op `onChange` mapt. Een handler direct op
  // de geslotte `<select>` vuurt daardoor nooit — het vakje verandert wel,
  // maar er wordt niets opgeslagen. `Select.tsx` relayed dat event en legt
  // in zijn eigen docstring uit waarom.
  return (
    <Select
      size="xs"
      width="140px"
      aria-label={`Drempel voor ${term}`}
      disabled={bezig}
      value={String(dichtstbijzijnde(waarde))}
      options={DREMPELS.map((d) => ({ value: String(d.waarde), label: d.label }))}
      onChange={(e) => onKies(Number(e.target.value))}
    />
  );
}

/**
 * De keuze die het dichtst bij de opgeslagen waarde ligt.
 *
 * De database kan elk getal 0-100 dragen (de API accepteert dat), dus de
 * dropdown zou leeg staan bij een waarde die niet exact in de lijst
 * voorkomt. Puur voor de weergave: er wordt alleen iets opgeslagen als de
 * gebruiker zelf kiest, dus een bewust gezette 35 blijft 35 tot iemand
 * hem aanraakt.
 */
function dichtstbijzijnde(waarde: number): number {
  return DREMPELS.reduce((beste, d) =>
    Math.abs(d.waarde - waarde) < Math.abs(beste.waarde - waarde) ? d : beste,
  ).waarde;
}
