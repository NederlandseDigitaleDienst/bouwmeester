import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from '@/components/nldd/Icon';
import { eventValue, orUndef, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import {
  getSignaalcontext,
  zetSignaalcontext,
} from '@/api/parlementairAbonnementen';

/**
 * De interne context die de prompts gebruiken om ruis te scheiden.
 *
 * Staat los van de beschrijving van het initiatief, en dat is de reden
 * dat dit veld bestaat: die beschrijving is publiek en vertelt een mens
 * wat het initiatief doet. Wat hier staat is afstelling van een
 * zoekmachine ("'fundament' is hier een projectnaam, niet de metafoor"),
 * en dat hoort niet op een publieke pagina.
 *
 * Eigen sectie in plaats van een uitklapper boven het termenveld: dit
 * geldt voor élke bron die signalen aandraagt, niet alleen voor
 * kamerstukken, en het is niet iets wat je bij elke term opnieuw doet.
 *
 * Ingeklapt toont hij de eerste regels van wat er staat, niet alleen een
 * knop. Wat het model weet over dit dossier is precies wat je wil zien
 * zonder te klikken.
 */
export function SignaalcontextSection({ initiatiefId }: { initiatiefId: string }) {
  const [open, setOpen] = useState(false);
  const [tekst, setTekst] = useState('');
  const [origineel, setOrigineel] = useState('');
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [bewaard, setBewaard] = useState(false);

  useEffect(() => {
    let actueel = true;
    getSignaalcontext(initiatiefId)
      .then((c) => {
        if (!actueel) return;
        setTekst(c.tekst);
        setOrigineel(c.tekst);
      })
      .catch(() => {
        // Stil: zonder context werkt alles, alleen minder scherp.
      });
    return () => {
      actueel = false;
    };
  }, [initiatiefId]);

  const opslaan = useCallback(async () => {
    if (bezig) return;
    setBezig(true);
    setFout(null);
    try {
      const c = await zetSignaalcontext(initiatiefId, tekst);
      setTekst(c.tekst);
      setOrigineel(c.tekst);
      setBewaard(true);
      setOpen(false);
    } catch {
      setFout('Opslaan is niet gelukt.');
    } finally {
      setBezig(false);
    }
  }, [bezig, initiatiefId, tekst]);

  const gewijzigd = tekst !== origineel;

  return (
    <nldd-card>
      <nldd-container gap="12" padding="16">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-container width="fit-content" className="row-fill">
            <nldd-container layout="row" gap="6" vertical-alignment="center">
              <Icon name="ai" size="sm" />
              <nldd-text size="xs" weight="bold" color="secondary">
                Context voor de beoordeling
              </nldd-text>
            </nldd-container>
          </nldd-container>
          {!open && (
            <nldd-button
              appearance="secondary"
              size="sm"
              text={origineel ? 'Aanpassen' : 'Toevoegen'}
              start-icon="edit"
              onClick={() => setOpen(true)}
            />
          )}
        </nldd-container>
        {fout && <nldd-banner variant="critical" size="sm" text={fout} />}

        {!open && (
          <>
            {origineel ? (
              <nldd-text size="sm">{eersteRegels(origineel)}</nldd-text>
            ) : (
              <nldd-text size="sm" color="secondary">
                Nog geen context. Het model beoordeelt nu alleen op de zoekterm
                zelf, en kan een projectnaam niet van een gewoon woord
                onderscheiden.
              </nldd-text>
            )}
            {bewaard && (
              <nldd-text size="xs" color="secondary">
                Opgeslagen. Geldt vanaf het volgende stuk dat binnenkomt.
              </nldd-text>
            )}
          </>
        )}

        {open && (
          <>
            <ContextVeld
              value={tekst}
              onChange={(v) => {
                setTekst(v);
                setBewaard(false);
              }}
            />
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <nldd-button
                appearance="secondary"
                size="sm"
                text="Opslaan"
                loading={orUndef(bezig)}
                disabled={orUndef(!gewijzigd)}
                onClick={opslaan}
              />
              <nldd-button
                appearance="neutral-transparent"
                size="sm"
                text="Annuleren"
                onClick={() => {
                  setTekst(origineel);
                  setOpen(false);
                  setFout(null);
                }}
              />
            </nldd-container>
          </>
        )}

        <nldd-text size="xs" color="secondary">
          Waar dit dossier over gaat, en vooral wat er niet bij hoort. Geldt voor
          elke bron, en staat niet op de publieke pagina.
        </nldd-text>
      </nldd-container>
    </nldd-card>
  );
}

/** De eerste regels, zodat de kaart toont wat het model weet. */
function eersteRegels(tekst: string): string {
  const plat = tekst.trim().replace(/\s+/g, ' ');
  return plat.length > 240 ? `${plat.slice(0, 240)}…` : plat;
}

/**
 * Het tekstveld zelf, met de waarde via een ref.
 *
 * Een web component neemt geen React-prop aan en vuurt een eigen event,
 * dus `value` en `input` lopen via `useNlddValue`/`useNlddEvent`, net als
 * bij `TermField`.
 */
function ContextVeld({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddValue(ref, value);
  useNlddEvent(
    ref,
    'input',
    useCallback((e: Event) => onChange(eventValue(e)), [onChange]),
  );
  return (
    <nldd-multi-line-text-field
      ref={ref}
      rows={10}
      maxlength={4000}
      accessible-label="Context voor het taalmodel"
      placeholder={
        'Bijvoorbeeld: "Fundament" is hier de naam van een project ' +
        '(Soevereine Overheidscloud). Niet relevant: "fundament" in ' +
        'figuurlijke zin, zoals "het fundament onder de begroting".'
      }
    />
  );
}
