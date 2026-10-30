import { useEffect, useRef, useState, type ReactNode } from 'react';

import { Input } from '@/components/common/Input';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useNlddEvent } from '@/components/nldd/events';
import { richTextToPlain } from '@/utils/richtext';

/*
 * Bouwstenen voor een detailvenster dat je direct bewerkt (taak,
 * onderzoeksvraag): eigenschappen als raster, een titel via het potloodje en
 * een lange tekst met Opslaan.
 */

/**
 * De eigenschappen in een detailvenster als raster: label boven de waarde, zoveel
 * kolommen als er passen. Bewust geen DetailMetadataGrid: die zet de waarde
 * in een `nldd-text`, en daarin krimpt een keuzelijst tot niets en breekt
 * tekst per woord af zodra het venster smal is (zoals in een zijpaneel).
 */
export function Eigenschappen({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(176px, 1fr))',
        gap: '16px',
        alignItems: 'start',
      }}
    >
      {children}
    </div>
  );
}

export function Eigenschap({ label, children, breed = false }: { label: string; children: ReactNode; breed?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0, ...(breed ? { gridColumn: '1 / -1' } : {}) }}>
      <nldd-text size="xs" weight="bold" color="secondary">{label}</nldd-text>
      {children}
    </div>
  );
}

/** Platte waarde in een eigenschap; `leeg` als er niets is. */
export function Waarde({ children, leeg }: { children?: ReactNode; leeg?: boolean }) {
  return leeg ? (
    <nldd-text size="sm" color="secondary">Geen</nldd-text>
  ) : (
    <nldd-text size="sm">{children}</nldd-text>
  );
}

/**
 * De titel, direct te bewerken: opslaan bij Enter of als je het veld verlaat.
 * Leeg maken mag niet; dan komt de oude titel terug.
 */
export function TitelVeld({
  titel,
  onOpslaan,
  onKlaar,
  zonderLabel = false,
}: {
  titel: string;
  onOpslaan: (titel: string) => void;
  /** Na opslaan, verlaten of Escape: het veld mag weer dicht. */
  onKlaar: () => void;
  /** In de kop staat het veld op de plek van de titel: daar is geen label nodig. */
  zonderLabel?: boolean;
}) {
  const ref = useRef<HTMLElement>(null);
  // Het veld gaat open via het potloodje; dan meteen typen. Het tekstveld
  // geeft focus door aan zijn eigen invoer, maar pas als het getekend is:
  // eerst wachten op `updateComplete`, dan een frame. Zonder dat bleef de
  // focus in het paneel, en sloot Escape het hele paneel.
  useEffect(() => {
    const el = ref.current as (HTMLElement & { updateComplete?: Promise<unknown> }) | null;
    if (!el) return;
    let weg = false;
    void (el.updateComplete ?? Promise.resolve()).then(() =>
      requestAnimationFrame(() => {
        if (!weg) el.focus();
      }),
    );
    return () => {
      weg = true;
    };
  }, []);
  // De tekst in het veld, met de titel waar hij van uitging: komt er een
  // nieuwe titel van de server, dan begint het veld daar opnieuw.
  const [concept, setConcept] = useState({ van: titel, tekst: titel });
  if (concept.van !== titel) setConcept({ van: titel, tekst: titel });
  // Enter en daarna het verlaten van het veld melden allebei; één keer opslaan.
  const laatst = useRef(titel);

  const bewaar = () => {
    const t = concept.tekst.trim();
    if (t && t !== titel && t !== laatst.current) {
      laatst.current = t;
      onOpslaan(t);
    }
    // Leeg of ongewijzigd: de titel blijft wat hij was.
    onKlaar();
  };
  useNlddEvent(ref, 'change', bewaar);

  return (
    <Input
      ref={ref}
      {...(zonderLabel ? { 'aria-label': 'Titel' } : { label: 'Titel' })}
      value={concept.tekst}
      onChange={(e) => setConcept({ van: concept.van, tekst: e.target.value })}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          bewaar();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          onKlaar();
        }
      }}
      required
    />
  );
}

/**
 * Een lange tekst (een beschrijving, een toelichting), altijd een editor.
 * Opslaan en Annuleren verschijnen pas als er iets veranderd is; de editor
 * meldt alleen wat je typt. Leeg opslaan bewaart null.
 */
export function TekstVeld({
  label,
  placeholder,
  tekst: opgeslagen,
  bezig,
  onOpslaan,
}: {
  label: string;
  placeholder: string;
  tekst: string;
  bezig: boolean;
  onOpslaan: (tekst: string | null) => Promise<void>;
}) {
  const [concept, setConcept] = useState({ van: opgeslagen, tekst: opgeslagen });
  if (concept.van !== opgeslagen) setConcept({ van: opgeslagen, tekst: opgeslagen });
  const gewijzigd = concept.tekst !== concept.van;

  return (
    <nldd-container gap="8">
      <RichTextFormField
        hideOptional
        label={label}
        value={concept.tekst}
        onChange={(tekst) => setConcept({ van: concept.van, tekst })}
        rows={4}
        placeholder={placeholder}
      />
      {gewijzigd && (
        <nldd-container layout="row" gap="8" horizontal-alignment="right">
          <NlddButton variant="neutral-transparent" size="sm" onClick={() => setConcept({ van: concept.van, tekst: concept.van })} text="Annuleren" />
          <NlddButton
            size="sm"
            loading={bezig}
            onClick={() => void onOpslaan(richTextToPlain(concept.tekst).trim() ? concept.tekst : null)}
            text="Opslaan"
          />
        </nldd-container>
      )}
    </nldd-container>
  );
}
