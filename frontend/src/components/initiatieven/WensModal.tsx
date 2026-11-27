import { useState } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { ViewToggle, type ViewToggleOption } from '@/components/common/ViewToggle';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useUpdateInitiatiefSettings } from '@/hooks/useInitiatieven';
import type { InitiatiefDetail, Wens } from '@/types';
import { todayISO } from '@/utils/dates';
import { richTextToPlain } from '@/utils/richtext';

import { GRENZEN, TOELICHTING_TE_LANG, WENSEN_VOL, opslaanFout } from './opslaanFout';

const SOORTEN: ViewToggleOption<Wens['soort']>[] = [
  { value: 'suggestie', label: 'Suggestie', icon: 'lightbulb' },
  { value: 'bug', label: 'Bug', icon: 'bug' },
];

/**
 * Een wens voor Bouwmeester toevoegen of bewerken, zoals je een
 * onderzoeksvraag toevoegt: een venster met soort, titel en toelichting.
 * Eerst kies je of het een suggestie of een bug is. Een nieuwe wens krijgt
 * je naam en de datum van vandaag. Bewerken kan ook verwijderen.
 *
 * Opslaan gaat via de instellingen van het initiatief (de hele lijst in één
 * keer), dus alleen de eigenaar. Lukt het niet, dan blijft het venster open
 * met de reden erin; een te lange toelichting zie je al vóór het versturen.
 */
export function WensModal({
  initiatief,
  wens,
  open,
  onClose,
}: {
  initiatief: InitiatiefDetail;
  /** Leeg: een nieuwe wens. */
  wens: Wens | null;
  open: boolean;
  onClose: () => void;
}) {
  if (!open) return null;
  // Elke keer een vers formulier.
  return <Formulier key={wens?.id ?? 'nieuw'} initiatief={initiatief} wens={wens} onClose={onClose} />;
}

function Formulier({ initiatief, wens, onClose }: { initiatief: InitiatiefDetail; wens: Wens | null; onClose: () => void }) {
  const settings = useUpdateInitiatiefSettings();
  const { currentPerson } = useCurrentPerson();
  const [soort, setSoort] = useState<Wens['soort']>(wens?.soort ?? 'suggestie');
  const [titel, setTitel] = useState(wens?.titel ?? '');
  const [toelichting, setToelichting] = useState(wens?.toelichting ?? '');
  const [weg, setWeg] = useState(false);
  const [fout, setFout] = useState('');
  const lijst = initiatief.wensen ?? [];

  const bewaar = async (nieuweLijst: Wens[]) => {
    setFout('');
    try {
      await settings.mutateAsync({ id: initiatief.id, data: { wensen: nieuweLijst } });
      onClose();
    } catch (e) {
      // Het venster blijft open, met de reden erin; het bevestigvenster gaat
      // dicht, zodat je die reden ook ziet.
      setWeg(false);
      setFout(opslaanFout(e));
    }
  };

  const opslaan = () => {
    const t = titel.trim();
    if (!t) return;
    const tekst = richTextToPlain(toelichting).trim() ? toelichting : null;
    // De grens telt de opgeslagen tekst, met opmaak; die ziet de gebruiker niet.
    if (tekst && tekst.length > GRENZEN.toelichting) {
      setFout(TOELICHTING_TE_LANG);
      return;
    }
    if (!wens && lijst.length >= GRENZEN.wensen) {
      setFout(WENSEN_VOL);
      return;
    }
    if (wens) {
      void bewaar(lijst.map((w) => (w.id === wens.id ? { ...w, soort, titel: t, toelichting: tekst } : w)));
    } else {
      void bewaar([
        ...lijst,
        {
          id: crypto.randomUUID(),
          soort,
          titel: t,
          toelichting: tekst,
          gemeld_door: currentPerson?.naam ?? null,
          // De datum van hier, niet die in UTC: rond middernacht scheelt dat een dag.
          gemeld_op: todayISO(),
        },
      ]);
    }
  };

  return (
    <>
      <Modal
        open
        onClose={onClose}
        title={wens ? 'Wens bewerken' : 'Wens toevoegen'}
        size="md"
        closeable={!settings.isPending}
        footer={
          <>
            {wens && (
              <NlddButton variant="neutral-transparent" startIcon="trash" onClick={() => setWeg(true)} text="Verwijderen" disabled={settings.isPending} />
            )}
            <NlddButton variant="secondary" onClick={onClose} text="Annuleren" disabled={settings.isPending} />
            <NlddButton onClick={opslaan} loading={settings.isPending} disabled={!titel.trim()} text={wens ? 'Opslaan' : 'Toevoegen'} />
          </>
        }
      >
        <nldd-container gap="16">
          <nldd-container gap="4">
            <nldd-text size="sm" weight="medium">
              Is het een suggestie of een bug?
            </nldd-text>
            <div>
              <ViewToggle value={soort} onChange={setSoort} options={SOORTEN} variant="text" accessibleLabel="Soort wens" />
            </div>
          </nldd-container>
          <Input
            label="Titel"
            type="text"
            value={titel}
            maxLength={300}
            onChange={(e) => setTitel(e.target.value)}
            placeholder={soort === 'bug' ? 'Wat gaat er mis?' : 'Wat wil je anders in Bouwmeester?'}
            required
          />
          <RichTextFormField
            hideOptional
            label="Toelichting"
            value={toelichting}
            onChange={setToelichting}
            rows={4}
            placeholder={
              soort === 'bug'
                ? 'Waar gebeurt het, wat deed je, en wat verwachtte je?'
                : 'Waarom zou dit helpen, en voor wie?'
            }
          />
          {fout && (
            <nldd-text size="sm" color="critical" role="alert">
              {fout}
            </nldd-text>
          )}
        </nldd-container>
      </Modal>
      <ConfirmDialog
        open={weg}
        onClose={() => setWeg(false)}
        onConfirm={() => void bewaar(lijst.filter((w) => w.id !== wens?.id))}
        title="Verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={settings.isPending}
      >
        {`"${wens?.titel ?? ''}" gaat van de lijst.`}
      </ConfirmDialog>
    </>
  );
}
