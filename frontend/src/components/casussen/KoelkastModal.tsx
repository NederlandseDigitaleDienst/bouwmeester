import { useCallback, useRef, useState } from 'react';

import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { NlddButton } from '@/components/nldd/NlddButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { useZetInKoelkast } from '@/hooks/useCasussen';
import type { Casus } from '@/types';
import { todayISO } from '@/utils/dates';

interface Props {
  /** De casus die in de koelkast gaat, of erin staat en bijgewerkt wordt; null is dicht. */
  casus: Casus | null;
  onClose: () => void;
}

/**
 * Een casus in de koelkast zetten. Verplicht: waarom hij erin gaat en
 * wanneer we verwachten dat hij er weer uit komt, zodat iedereen dat ziet
 * op het kaartje. Staat hij er al in, dan werk je hier de reden en datum
 * bij. De fase blijft staan.
 */
export function KoelkastModal({ casus, onClose }: Props) {
  if (!casus) return null;
  return <Formulier key={casus.id} casus={casus} onClose={onClose} />;
}

function Formulier({ casus, onClose }: { casus: Casus; onClose: () => void }) {
  const zet = useZetInKoelkast();
  const [reden, setReden] = useState(casus.koelkast_reden ?? '');
  const [terug, setTerug] = useState(casus.koelkast_verwacht_terug ?? '');
  const [geprobeerd, setGeprobeerd] = useState(false);
  const al = !!casus.koelkast_sinds;
  const vandaag = todayISO();
  const redenFout = !reden.trim() ? 'Zeg waarom de casus in de koelkast gaat.' : null;
  const terugFout = !terug
    ? 'Kies wanneer je verwacht dat hij er weer uit komt.'
    : terug < vandaag
      ? 'Die datum is al voorbij.'
      : null;

  const opslaan = async () => {
    setGeprobeerd(true);
    if (redenFout || terugFout) return;
    try {
      await zet.mutateAsync({ id: casus.id, data: { reden: reden.trim(), verwacht_terug: terug } });
      onClose();
    } catch {
      // de melding is al getoond; het venster blijft open
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={al ? 'Koelkast bijwerken' : 'In de koelkast'}
      entityLabel={casus.title}
      closeable={!zet.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" disabled={zet.isPending} />
          <NlddButton onClick={() => void opslaan()} loading={zet.isPending} text={al ? 'Opslaan' : 'In de koelkast zetten'} />
        </>
      }
    >
      <nldd-container gap="16">
        <nldd-text size="sm" color="secondary">
          De casus ligt even stil. Hij houdt zijn fase en gaat daar verder als hij uit de koelkast komt.
        </nldd-text>
        <RedenVeld value={reden} onChange={setReden} fout={geprobeerd ? redenFout : null} />
        <Input
          type="date"
          label="Wanneer verwacht je dat hij er weer uit komt?"
          required
          value={terug}
          onChange={(e) => setTerug(e.target.value)}
          error={geprobeerd ? terugFout ?? undefined : undefined}
        />
      </nldd-container>
    </Modal>
  );
}

function RedenVeld({ value, onChange, fout }: { value: string; onChange: (v: string) => void; fout: string | null }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(
    ref,
    'input',
    useCallback((e: Event) => onChange(eventValue(e)), [onChange]),
  );
  return (
    <nldd-form-field label="Waarom gaat hij in de koelkast?">
      <nldd-multi-line-text-field
        ref={ref}
        value={value}
        rows={3}
        maxlength={2000}
        placeholder="Bijvoorbeeld: de partner heeft tot na de zomer geen tijd"
        width="full"
        {...(fout ? { invalid: true as const } : {})}
      />
      {fout && <nldd-text size="sm" color="critical">{fout}</nldd-text>}
    </nldd-form-field>
  );
}
