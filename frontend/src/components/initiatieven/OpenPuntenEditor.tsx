import { useEffect, useState } from 'react';

import { NlddButton } from '@/components/nldd/NlddButton';
import { useUpdateInitiatiefSettings } from '@/hooks/useInitiatieven';
import type { InitiatiefDetail } from '@/types';
import { EisenLijst } from './EisenLijst';

/**
 * Op de tab RegelRitme, onder de lijst zelf: de punten die nog openstaan
 * aanpassen. Opslaan in één keer, zoals bij de acceptatiecriteria;
 * Annuleren zet terug wat er stond en sluit.
 */
export function OpenPuntenEditor({
  initiatief,
  onKlaar,
}: {
  initiatief: InitiatiefDetail;
  /** Na opslaan of annuleren: de lijst weer gewoon tonen. */
  onKlaar: () => void;
}) {
  const settings = useUpdateInitiatiefSettings();
  const opgeslagen = initiatief.open_punten ?? [];
  const [punten, setPunten] = useState<string[]>(opgeslagen);

  // Na opslaan of een herlaadactie de server volgen.
  const sleutel = JSON.stringify(opgeslagen);
  useEffect(() => {
    setPunten(JSON.parse(sleutel) as string[]);
  }, [sleutel]);

  const schoon = punten.map((p) => p.trim()).filter(Boolean);
  const dirty = JSON.stringify(schoon) !== JSON.stringify(opgeslagen);

  return (
    <nldd-container gap="20">
      <nldd-container gap="8">
        <nldd-text size="xs" color="secondary">
          Wat het team nog moet bespreken of besluiten. Is iets besloten, haal het dan uit de lijst.
        </nldd-text>
        <EisenLijst
          items={punten}
          onChange={setPunten}
          naam="Punt"
          placeholder="Nieuw punt, bijvoorbeeld: de Definition of Done samen vaststellen"
          leeg="Er staan geen punten open."
          nieuwLabel="Nieuw punt"
        />
      </nldd-container>
      <nldd-container layout="row" gap="8" horizontal-alignment="right">
        <NlddButton variant="secondary" size="sm" onClick={onKlaar} text="Annuleren" />
        <NlddButton
          size="sm"
          loading={settings.isPending}
          disabled={!dirty}
          onClick={() => settings.mutate({ id: initiatief.id, data: { open_punten: schoon } }, { onSuccess: onKlaar })}
          text="Opslaan"
        />
      </nldd-container>
    </nldd-container>
  );
}
