import { useState } from 'react';

import { Badge } from '@/components/common/Badge';
import { Input } from '@/components/common/Input';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { NlddButton } from '@/components/nldd/NlddButton';
import { usePublishIssue, useUnpublishIssue } from '@/hooks/useIssues';
import { IssueStatus, type VraagVoorBuiten } from '@/types';
import { richTextToPlain } from '@/utils/richtext';

/**
 * Een @- of #-verwijzing uit de editor ([@Naam](user:id), [#Taak](task:id)).
 * Die noemt een persoon of intern werk; de backend weigert hem in een
 * publieke tekst, en het formulier zegt dat al tijdens het typen.
 */
const VERWIJZING = /\]\((?:user|org|node|task):/i;

/**
 * Een afgeronde onderzoeksvraag naar buiten brengen, in het paneel van de
 * vraag. Casussen zijn nooit publiek: alleen de vraag en het antwoord die je
 * hier schrijft gaan naar buiten, op de publieke pagina en in de mailbrief
 * van een update. Vrijgeven is een bewuste stap met een eigen knop.
 *
 * Een open vraag krijgt alleen een korte uitleg; heropenen trekt een
 * vrijgegeven vraag vanzelf in (de backend doet dat), de tekst blijft dan
 * bewaard.
 */
export function NaarBuiten({ issue }: { issue: VraagVoorBuiten }) {
  if (!issue.is_onderzoeksvraag) return null;
  if (issue.status !== IssueStatus.DONE) {
    return (
      <nldd-container gap="4">
        <nldd-text size="md" weight="medium">
          Antwoord, externe versie
        </nldd-text>
        <nldd-text size="sm" color="secondary">
          Is de vraag afgerond, dan schrijf je hier de versie voor buiten: een publieke vraag en een kort antwoord. Na
          vrijgeven staat die in de updates en op de publieke pagina, en straks op de roadmap.
        </nldd-text>
      </nldd-container>
    );
  }
  return <Formulier issue={issue} />;
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
  const verwijzing = VERWIJZING.test(concept.vraag) || VERWIJZING.test(concept.antwoord);
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
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <nldd-text size="md" weight="medium">
          Antwoord, externe versie
        </nldd-text>
        {vrijgegeven ? (
          <Badge color="groen">{`Vrijgegeven op ${new Date(issue.published_at!).toLocaleDateString('nl-NL')}`}</Badge>
        ) : (
          <Badge color="coolgray">Binnen</Badge>
        )}
      </nldd-container>
      <nldd-text size="sm" color="secondary">
        Alleen deze vraag en dit antwoord gaan naar buiten: in de updates, op de publieke pagina en straks op de
        roadmap. De casus, de titel, de toelichting en de interne versie blijven binnen. Schrijf voor iemand die de
        casus niet kent, zonder namen of interne details.
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
          Haal de verwijzingen met @ of # weg. Die noemen een persoon, organisatie of intern werk, en dat gaat niet naar
          buiten.
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
