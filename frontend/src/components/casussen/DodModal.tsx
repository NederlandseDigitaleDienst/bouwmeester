import { useEffect, useRef, useState } from 'react';

import { Modal } from '@/components/common/Modal';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCasus } from '@/hooks/useCasussen';
import { useUpdateIssue } from '@/hooks/useIssues';
import { IssueStatus } from '@/types';

/** Wat de DoD van een issue nodig heeft; een Issue en een BacklogIssue passen allebei. */
export interface DodIssue {
  id: string;
  casus_id: string;
  title: string;
  dod_checked: string[];
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
 * casus (die van het initiatief, anders de standaardlijst). Afronden zet het
 * issue op afgerond met de afgevinkte eisen: alleen zo wordt een issue af,
 * ook als alle taken eronder al klaar zijn.
 */
export function DodModal({ issue, mode, onClose }: Props) {
  const { data: casus } = useCasus(issue?.casus_id ?? null);
  const update = useUpdateIssue();
  const dodItems = casus?.dod_items ?? [];
  const [checked, setChecked] = useState<Set<string>>(new Set());

  useEffect(() => {
    setChecked(new Set(issue?.dod_checked ?? []));
  }, [issue?.id, issue?.dod_checked]);

  const toggle = (item: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });

  const open = dodItems.filter((i) => !checked.has(i)).length;

  const afronden = async () => {
    if (!issue) return;
    try {
      await update.mutateAsync({
        casusId: issue.casus_id,
        issueId: issue.id,
        data: { status: IssueStatus.DONE, dod_checked: dodItems.filter((i) => checked.has(i)) },
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
              disabled={!casus}
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
        {!casus ? (
          <nldd-text size="sm" color="secondary">Laden...</nldd-text>
        ) : (
          <nldd-container gap="8">
            {dodItems.map((item) => (
              <DodCheck
                key={item}
                label={item}
                checked={checked.has(item)}
                disabled={mode === 'bekijken'}
                onToggle={() => toggle(item)}
              />
            ))}
          </nldd-container>
        )}
        {mode === 'afronden' && casus && open > 0 && (
          <nldd-text size="xs" color="secondary">
            Nog {open} van {dodItems.length} eisen niet afgevinkt. Afronden kan, maar dan staat dat
            zo op het issue.
          </nldd-text>
        )}
      </nldd-container>
    </Modal>
  );
}

function DodCheck({
  label,
  checked,
  disabled,
  onToggle,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', onToggle);
  return (
    <nldd-checkbox-field
      ref={ref}
      checked={orUndef(checked)}
      disabled={orUndef(disabled)}
      label={label}
    />
  );
}
