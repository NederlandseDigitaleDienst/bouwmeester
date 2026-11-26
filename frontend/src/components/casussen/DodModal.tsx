import { useContext, useEffect, useRef, useState } from 'react';

import { Modal } from '@/components/common/Modal';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useDodItems } from '@/hooks/useDodItems';
import { InitiatiefIdContext } from '@/hooks/useInitiatiefPersonOptions';
import { useUpdateIssue } from '@/hooks/useIssues';
import { IssueStatus } from '@/types';
import { richTextToPlain } from '@/utils/richtext';

/** Wat de DoD van een issue nodig heeft; een Issue en een BacklogIssue passen allebei. */
export interface DodIssue {
  id: string;
  /** Leeg bij een vraag zonder casus; dan telt initiatief_id. */
  casus_id: string | null;
  initiatief_id?: string | null;
  title: string;
  /** Alleen een onderzoeksvraag krijgt bij het afronden een antwoord. */
  is_onderzoeksvraag: boolean;
  dod_checked: string[];
  antwoord?: string | null;
}

interface Props {
  issue: DodIssue | null;
  /** Alleen kijken (issue is al af) of afronden. */
  mode: 'afronden' | 'bekijken';
  onClose: () => void;
}

/**
 * De Definition of Done bij het afronden van een issue: de teamstandaard als
 * checklist. Het team beslist zelf of alles moet staan; de knop blijft
 * beschikbaar, maar de tekst zegt wat er nog open is. De lijst komt van de
 * casus (die van het initiatief, anders de standaardlijst); een vraag zonder
 * casus neemt hem van het initiatief. Afronden zet het
 * issue op afgerond met de afgevinkte eisen: alleen zo wordt een issue af,
 * ook als alle taken eronder al klaar zijn.
 */
export function DodModal({ issue, mode, onClose }: Props) {
  const initiatiefId = useContext(InitiatiefIdContext);
  const update = useUpdateIssue();
  const geladenItems = useDodItems(issue?.casus_id, issue?.initiatief_id ?? initiatiefId);
  const geladen = geladenItems !== undefined;
  const dodItems = geladenItems ?? [];
  const [checked, setChecked] = useState<Set<string>>(new Set());

  // Bij afronden van een onderzoeksvraag: het antwoord, interne versie, voor het team.
  // De externe versie volgt daarna in het vraagpaneel (Naar buiten).
  const metAntwoord = mode === 'afronden' && !!issue?.is_onderzoeksvraag;
  const [antwoord, setAntwoord] = useState(issue?.antwoord ?? '');
  useEffect(() => {
    setChecked(new Set(issue?.dod_checked ?? []));
  }, [issue?.id, issue?.dod_checked]);
  useEffect(() => {
    setAntwoord(issue?.antwoord ?? '');
  }, [issue?.id, issue?.antwoord]);

  const zet = (item: string, aan: boolean) =>
    setChecked((prev) => {
      if (prev.has(item) === aan) return prev;
      const next = new Set(prev);
      if (aan) next.add(item);
      else next.delete(item);
      return next;
    });

  const open = dodItems.filter((i) => !checked.has(i)).length;

  const afronden = async () => {
    if (!issue) return;
    try {
      await update.mutateAsync({
        plek: issue,
        issueId: issue.id,
        data: {
          status: IssueStatus.DONE,
          dod_checked: dodItems.filter((i) => checked.has(i)),
          // Een issue dat geen onderzoeksvraag is, houdt zijn antwoord zoals het is.
          ...(metAntwoord ? { antwoord: richTextToPlain(antwoord).trim() ? antwoord : null } : {}),
        },
      });
      onClose();
    } catch {
      // toast is al getoond; het venster blijft open
    }
  };

  return (
    <Modal
      open={!!issue}
      onClose={onClose}
      title={mode === 'afronden' ? 'Onderzoeksvraag afronden' : 'Definition of Done'}
      size="md"
      closeable={!update.isPending}
      footer={
        mode === 'afronden' ? (
          <>
            <NlddButton variant="secondary" onClick={onClose} text="Annuleren" />
            <NlddButton
              onClick={() => void afronden()}
              loading={update.isPending}
              disabled={!geladen}
              text={open === 0 ? 'Afronden' : `Afronden met ${open} open`}
            />
          </>
        ) : (
          <NlddButton variant="secondary" onClick={onClose} text="Sluiten" />
        )
      }
    >
      <nldd-container gap="12">
        {issue && (
          <nldd-text size="sm" weight="medium">{issue.title}</nldd-text>
        )}
        <nldd-text size="sm" color="secondary">
          De Definition of Done is de teamstandaard: waar een issue aan moet voldoen voordat
          het af is. Aan te passen bij de instellingen van het initiatief.
        </nldd-text>
        {!geladen ? (
          <nldd-text size="sm" color="secondary">Laden...</nldd-text>
        ) : (
          <nldd-container gap="8">
            {dodItems.map((item) => (
              <DodCheck
                key={item}
                label={item}
                checked={checked.has(item)}
                disabled={mode === 'bekijken'}
                onChange={(aan) => zet(item, aan)}
              />
            ))}
          </nldd-container>
        )}
        {mode === 'afronden' && geladen && open > 0 && (
          <nldd-text size="xs" color="secondary">
            Nog {open} van {dodItems.length} eisen niet afgevinkt. Afronden kan, maar dan staat dat
            zo op het issue.
          </nldd-text>
        )}
        {metAntwoord && (
          <RichTextFormField
            hideOptional
            label="Antwoord, interne versie"
            value={antwoord}
            onChange={setAntwoord}
            rows={4}
            placeholder="Wat is het antwoord? Voor het team, met namen en details als dat helpt."
          />
        )}
      </nldd-container>
    </Modal>
  );
}

function DodCheck({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (aan: boolean) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  // nldd-checkbox-field meldt één klik twee keer, met dezelfde stand. Omkeren
  // per melding zette het vinkje meteen weer terug; de stand uit de melding
  // overnemen maakt de tweede melding onschadelijk.
  useNlddEvent(ref, 'change', (e) => onChange(Boolean((e as CustomEvent<{ checked?: boolean }>).detail?.checked)));
  return (
    <nldd-checkbox-field
      ref={ref}
      checked={orUndef(checked)}
      disabled={orUndef(disabled)}
      label={label}
    />
  );
}
