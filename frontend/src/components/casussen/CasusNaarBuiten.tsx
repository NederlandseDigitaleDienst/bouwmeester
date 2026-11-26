import { useState } from 'react';

import { Badge } from '@/components/common/Badge';
import { TekstVeld } from '@/components/common/DetailVelden';
import { Input } from '@/components/common/Input';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { NlddButton } from '@/components/nldd/NlddButton';
import { usePublishCasus, useUnpublishCasus, useUpdateCasus } from '@/hooks/useCasussen';
import type { KlaarCasus } from '@/types';
import { heeftVerwijzing, VERWIJZING_MELDING } from '@/utils/publiekeTekst';
import { richTextToPlain } from '@/utils/richtext';

/**
 * Een afgeronde casus: de lessen (binnen) en de tekst voor buiten. De casus
 * zelf gaat nooit naar buiten; alleen de naam, het resultaat en de lessen
 * die je hier voor buiten schrijft, en pas na Vrijgeven. Haalt iemand de
 * casus uit de laatste fase, of komt er een fase achter, dan is hij niet
 * meer vrijgegeven.
 *
 * Wijzigen en vrijgeven staan er alleen voor een bijdrager of eigenaar van
 * het initiatief (`kanWijzigen`), zoals de backend het controleert. Een
 * ander ziet de lessen en wat er buiten staat, zonder velden en knoppen.
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
  const verwijzing = heeftVerwijzing(concept.titel, concept.resultaat, concept.lessen);
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

  if (!kanWijzigen) return <AlleenLezen casus={casus} />;

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
        <Kop casus={casus} />
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
            {VERWIJZING_MELDING}
          </nldd-text>
        )}
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
      </nldd-container>
    </nldd-container>
  );
}

function Kop({ casus }: { casus: KlaarCasus }) {
  return (
    <nldd-container layout="row" gap="8" vertical-alignment="center">
      <nldd-text size="md" weight="medium">
        Naar buiten
      </nldd-text>
      {casus.published_at ? (
        <Badge color="groen">{`Vrijgegeven op ${new Date(casus.published_at).toLocaleDateString('nl-NL')}`}</Badge>
      ) : (
        <Badge color="coolgray">Binnen</Badge>
      )}
    </nldd-container>
  );
}

/** Voor wie niet mag vrijgeven: de lessen en wat er buiten staat, zonder knoppen. */
function AlleenLezen({ casus }: { casus: KlaarCasus }) {
  return (
    <nldd-container gap="24">
      <nldd-container gap="4">
        <nldd-text size="sm" weight="medium">
          Wat hebben we geleerd? (blijft binnen)
        </nldd-text>
        {casus.lessen ? (
          <RichTextDisplay content={casus.lessen} />
        ) : (
          <nldd-text size="sm" color="secondary">
            Nog geen lessen vastgelegd.
          </nldd-text>
        )}
      </nldd-container>
      <nldd-container gap="8">
        <Kop casus={casus} />
        {casus.published_at && (
          <nldd-container gap="4">
            <nldd-text size="sm" weight="medium">
              {casus.public_title ?? ''}
            </nldd-text>
            <RichTextDisplay content={casus.public_resultaat} />
            {casus.public_lessen && <RichTextDisplay content={casus.public_lessen} />}
          </nldd-container>
        )}
        <nldd-text size="sm" color="secondary">
          Vrijgeven voor buiten kan een bijdrager of eigenaar van het initiatief.
        </nldd-text>
      </nldd-container>
    </nldd-container>
  );
}
