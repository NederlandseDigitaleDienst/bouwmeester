import { useState } from 'react';

import { Badge } from '@/components/common/Badge';
import { TekstVeld } from '@/components/common/DetailVelden';
import { Input } from '@/components/common/Input';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { NlddButton } from '@/components/nldd/NlddButton';
import { usePublishCasus, useUnpublishCasus, useUpdateCasus } from '@/hooks/useCasussen';
import type { KlaarCasus } from '@/types';
import { richTextToPlain } from '@/utils/richtext';

/** Een @- of #-verwijzing uit de editor; de backend weigert hem in een publieke tekst. */
const VERWIJZING = /\]\((?:user|org|node|task):/i;

/**
 * Een afgeronde casus: de lessen (binnen) en de tekst voor buiten. Casussen
 * zijn nooit publiek; alleen de naam, het resultaat en de lessen die je hier
 * voor buiten schrijft gaan naar buiten, en pas na Vrijgeven. Haalt iemand
 * de casus uit de laatste fase, dan is hij niet meer vrijgegeven.
 */
export function CasusNaarBuiten({ casus, kanWijzigen }: { casus: KlaarCasus; kanWijzigen: boolean }) {
  const update = useUpdateCasus();
  const publish = usePublishCasus();
  const unpublish = useUnpublishCasus();
  const opgeslagen = {
    titel: casus.public_title ?? '',
    resultaat: casus.public_resultaat ?? '',
    lessen: casus.public_lessen ?? '',
  };
  const [concept, setConcept] = useState(opgeslagen);
  const vrijgegeven = !!casus.published_at;
  const gewijzigd =
    concept.titel !== opgeslagen.titel ||
    concept.resultaat !== opgeslagen.resultaat ||
    concept.lessen !== opgeslagen.lessen;
  const verwijzing = [concept.titel, concept.resultaat, concept.lessen].some((t) => VERWIJZING.test(t));
  const compleet = concept.titel.trim() !== '' && richTextToPlain(concept.resultaat).trim() !== '' && !verwijzing;

  const bewaarLessen = async (lessen: string | null) => {
    try {
      await update.mutateAsync({ id: casus.id, data: { lessen } });
    } catch {
      // de melding is al getoond; de tekst blijft staan
    }
  };

  const geefVrij = async () => {
    try {
      await publish.mutateAsync({
        id: casus.id,
        data: {
          public_title: concept.titel.trim(),
          public_resultaat: concept.resultaat,
          public_lessen: richTextToPlain(concept.lessen).trim() ? concept.lessen : null,
        },
      });
    } catch {
      // de melding is al getoond; de tekst blijft staan
    }
  };

  return (
    <nldd-container gap="24">
      <TekstVeld
        label="Wat hebben we geleerd? (blijft binnen)"
        placeholder="Wat nemen we mee naar de volgende casus? Wat zouden we anders doen?"
        tekst={casus.lessen ?? ''}
        bezig={update.isPending}
        onOpslaan={bewaarLessen}
      />

      <nldd-container gap="8">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-text size="md" weight="medium">
            Naar buiten
          </nldd-text>
          {vrijgegeven ? (
            <Badge color="groen">{`Vrijgegeven op ${new Date(casus.published_at!).toLocaleDateString('nl-NL')}`}</Badge>
          ) : (
            <Badge color="coolgray">Binnen</Badge>
          )}
        </nldd-container>
        <nldd-text size="sm" color="secondary">
          Alleen wat je hieronder schrijft gaat naar buiten, op de publieke pagina en in de mailbrief van een update. De
          casus zelf, zijn naam binnen, het team en de lessen hierboven blijven binnen. Schrijf voor iemand die de casus
          niet kent, zonder namen of interne details.
        </nldd-text>
        <Input
          label="Naam voor buiten"
          required
          value={concept.titel}
          maxLength={500}
          onChange={(e) => setConcept({ ...concept, titel: e.target.value })}
        />
        <RichTextFormField
          hideOptional
          label="Wat het opleverde"
          value={concept.resultaat}
          onChange={(resultaat) => setConcept({ ...concept, resultaat })}
          rows={3}
          placeholder="Wat is er nu, dat er eerst niet was?"
        />
        <RichTextFormField
          label="Lessen voor buiten"
          value={concept.lessen}
          onChange={(lessen) => setConcept({ ...concept, lessen })}
          rows={3}
          placeholder="Welke les delen we met anderen? Laat leeg als je niets deelt."
        />
        {verwijzing && (
          <nldd-text size="xs" color="critical">
            Haal de verwijzingen met @ of # weg. Die noemen een persoon, organisatie of intern werk, en dat gaat niet
            naar buiten.
          </nldd-text>
        )}
        {kanWijzigen && (
          <nldd-container layout="row" gap="8" horizontal-alignment="right">
            {vrijgegeven && (
              <NlddButton
                variant="neutral-transparent"
                size="sm"
                loading={unpublish.isPending}
                onClick={() => unpublish.mutate({ id: casus.id })}
                text="Intrekken"
              />
            )}
            {vrijgegeven ? (
              gewijzigd && (
                <NlddButton
                  size="sm"
                  loading={publish.isPending}
                  disabled={!compleet}
                  onClick={geefVrij}
                  text="Tekst opslaan"
                />
              )
            ) : (
              <NlddButton
                size="sm"
                loading={publish.isPending}
                disabled={!compleet}
                onClick={geefVrij}
                text="Vrijgeven"
              />
            )}
          </nldd-container>
        )}
      </nldd-container>
    </nldd-container>
  );
}
