import { useState } from 'react';

import { DetailSection } from '@/components/common/DetailSection';
import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useUpdateCirkel } from '@/hooks/useInitiatiefRollen';
import type { InitiatiefCirkel } from '@/types';
import { EisenLijst } from '../EisenLijst';

/**
 * De cirkel van het initiatief: zijn doel en waar hij nu op focust. Vrije
 * regels; waar de focus later verder landt, is nog open.
 */
export function CirkelPaneel({
  initiatiefId,
  cirkel,
  canEdit,
  onClose,
}: {
  initiatiefId: string;
  cirkel: InitiatiefCirkel;
  canEdit: boolean;
  onClose: () => void;
}) {
  const update = useUpdateCirkel();
  const [bewerken, setBewerken] = useState(false);
  const [doel, setDoel] = useState(cirkel.doel ?? '');
  const [focus, setFocus] = useState<string[]>(cirkel.focus);

  const opslaan = async () => {
    try {
      await update.mutateAsync({
        initiatiefId,
        data: { doel: doel.trim() || null, focus: focus.map((f) => f.trim()).filter(Boolean) },
      });
      setBewerken(false);
    } catch {
      // de melding is al getoond
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={cirkel.naam}
      entityLabel="Cirkel"
      size="lg"
      placement="right"
      dismissText="Sluit"
      closeable={!update.isPending}
      toolbar={
        canEdit && !bewerken ? (
          <NlddButton variant="neutral-transparent" size="sm" startIcon="pencil" onClick={() => setBewerken(true)} text="Bewerken" />
        ) : undefined
      }
      footer={
        bewerken ? (
          <>
            <NlddButton
              variant="secondary"
              onClick={() => {
                setDoel(cirkel.doel ?? '');
                setFocus(cirkel.focus);
                setBewerken(false);
              }}
              text="Annuleren"
              disabled={update.isPending}
            />
            <NlddButton onClick={() => void opslaan()} loading={update.isPending} text="Opslaan" />
          </>
        ) : undefined
      }
    >
      {bewerken ? (
        <nldd-container gap="20">
          <Input
            type="text"
            label="Doel"
            value={doel}
            maxLength={2000}
            placeholder="Waar deze cirkel voor is"
            onChange={(e) => setDoel(e.target.value)}
          />
          <nldd-container gap="8">
            <nldd-text size="sm" weight="bold">Focus</nldd-text>
            <EisenLijst
              items={focus}
              onChange={setFocus}
              naam="Focuspunt"
              placeholder="Bijvoorbeeld: referentiecasus 1 afronden"
              leeg="Nog geen focus. Voeg hieronder een punt toe."
              nieuwLabel="Nieuw focuspunt"
              max={20}
            />
          </nldd-container>
        </nldd-container>
      ) : (
        <nldd-container gap="20">
          <DetailSection title="Doel">
            <nldd-text size="sm">{cirkel.doel || 'Nog geen doel.'}</nldd-text>
          </DetailSection>
          <DetailSection title="Focus" count={cirkel.focus.length}>
            {cirkel.focus.length === 0 ? (
              <nldd-text size="sm" color="secondary">Nog geen focus.</nldd-text>
            ) : (
              <nldd-rich-text>
                <ul>
                  {cirkel.focus.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </nldd-rich-text>
            )}
          </DetailSection>
        </nldd-container>
      )}
    </Modal>
  );
}
