import { useState } from 'react';

import { Badge } from '@/components/common/Badge';
import { Input } from '@/components/common/Input';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { NlddButton } from '@/components/nldd/NlddButton';
import { usePublishIssue, useUnpublishIssue } from '@/hooks/useIssues';
import { IssueStatus, type VraagVoorBuiten } from '@/types';
import { heeftVerwijzing, VERWIJZING_MELDING } from '@/utils/publiekeTekst';
import { richTextToPlain } from '@/utils/richtext';

/**
 * Een afgeronde onderzoeksvraag naar buiten brengen, in het paneel van de
 * vraag. De casus gaat nooit naar buiten: alleen de vraag en het antwoord
 * die je hier schrijft, op de publieke pagina en in de mailbrief van een
 * update. Vrijgeven is een bewuste stap met een eigen knop.
 *
 * Vrijgeven, de tekst wijzigen en intrekken staan er alleen voor wie mag
 * vrijgeven: een bijdrager of eigenaar van het initiatief, zoals de backend
 * het controleert (`require_can_publish_issue`). Een ander ziet wat er
 * buiten staat, zonder knoppen.
 *
 * Een open vraag krijgt alleen een korte uitleg; heropenen trekt een
 * vrijgegeven vraag vanzelf in (de backend doet dat), de tekst blijft dan
 * bewaard.
 */
export function NaarBuiten({ issue, kanVrijgeven }: { issue: VraagVoorBuiten; kanVrijgeven: boolean }) {
  if (!issue.is_onderzoeksvraag) return null;
  if (issue.status !== IssueStatus.DONE) {
    return (
      <nldd-container gap="4">
        <nldd-text size="md" weight="medium">
          Antwoord, externe versie
        </nldd-text>
        <nldd-text size="sm" color="secondary">
          Is de vraag afgerond, dan schrijf je hier de versie voor buiten: een publieke vraag en een kort antwoord. Na
          vrijgeven kan die mee in een update en staat hij op de publieke pagina.
        </nldd-text>
      </nldd-container>
    );
  }
  return kanVrijgeven ? <Formulier issue={issue} /> : <AlleenLezen issue={issue} />;
}

function Kop({ issue }: { issue: VraagVoorBuiten }) {
  return (
    <nldd-container layout="row" gap="8" vertical-alignment="center">
      <nldd-text size="md" weight="medium">
        Antwoord, externe versie
      </nldd-text>
      {issue.published_at ? (
        <Badge color="groen">{`Vrijgegeven op ${new Date(issue.published_at).toLocaleDateString('nl-NL')}`}</Badge>
      ) : (
        <Badge color="coolgray">Binnen</Badge>
      )}
    </nldd-container>
  );
}

/** Voor wie niet mag vrijgeven: wat er buiten staat, zonder knoppen. */
function AlleenLezen({ issue }: { issue: VraagVoorBuiten }) {
  return (
    <nldd-container gap="8">
      <Kop issue={issue} />
      {issue.published_at && (
        <nldd-container gap="4">
          <nldd-text size="sm" weight="medium">
            {issue.public_title ?? ''}
          </nldd-text>
          <RichTextDisplay content={issue.public_answer} />
        </nldd-container>
      )}
      <nldd-text size="sm" color="secondary">
        Vrijgeven voor buiten kan een bijdrager of eigenaar van het initiatief.
      </nldd-text>
    </nldd-container>
  );
}

function Formulier({ issue }: { issue: VraagVoorBuiten }) {
  const publish = usePublishIssue();
  const unpublish = useUnpublishIssue();
  const opgeslagen = {
    vraag: issue.public_title ?? '',
    antwoord: issue.public_answer ?? '',
  };
  const [concept, setConcept] = useState(opgeslagen);
  const vrijgegeven = !!issue.published_at;
  const gewijzigd = concept.vraag !== opgeslagen.vraag || concept.antwoord !== opgeslagen.antwoord;
  const verwijzing = heeftVerwijzing(concept.vraag, concept.antwoord);
  const compleet = concept.vraag.trim() !== '' && richTextToPlain(concept.antwoord).trim() !== '' && !verwijzing;

  const geefVrij = async () => {
    try {
      await publish.mutateAsync({
        plek: issue,
        issueId: issue.id,
        data: {
          public_title: concept.vraag.trim(),
          public_answer: concept.antwoord,
        },
      });
    } catch {
      // de melding is al getoond; de tekst blijft staan
    }
  };

  return (
    <nldd-container gap="8">
      <Kop issue={issue} />
      <nldd-text size="sm" color="secondary">
        Alleen deze vraag en dit antwoord gaan naar buiten: in de updates, de mailbrief en op de publieke pagina. De
        casus, de titel, de toelichting en de interne versie blijven binnen. Schrijf voor iemand die de casus niet
        kent, zonder namen of interne details.
      </nldd-text>
      <Input
        label="Vraag voor buiten"
        required
        value={concept.vraag}
        maxLength={1000}
        onChange={(e) => setConcept({ ...concept, vraag: e.target.value })}
      />
      <RichTextFormField
        hideOptional
        label="Kort antwoord"
        value={concept.antwoord}
        onChange={(antwoord) => setConcept({ ...concept, antwoord })}
        rows={3}
        placeholder="Wat is het antwoord, in twee of drie zinnen?"
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
            onClick={() => unpublish.mutate({ plek: issue, issueId: issue.id })}
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
          <NlddButton size="sm" loading={publish.isPending} disabled={!compleet} onClick={geefVrij} text="Vrijgeven" />
        )}
      </nldd-container>
    </nldd-container>
  );
}
