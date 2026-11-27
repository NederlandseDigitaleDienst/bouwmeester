import { useState } from 'react';

import { Modal } from '@/components/common/Modal';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useUpdateCasus } from '@/hooks/useCasussen';
import type { Casus } from '@/types';
import { EisenNalopen } from './EisenNalopen';
import { naarSoortEisen, uitMomentopname, zetEis, type EisWaarden } from './eisen';

interface Props {
  /** De casus die naar de laatste fase gaat; null is dicht. */
  casus: Casus | null;
  /** De laatste fase van de casusfunnel. */
  fase: { id: string; naam: string } | null;
  onClose: () => void;
}

/**
 * Een casus naar de laatste fase van de funnel: eerst de eindeisen van zijn
 * soorten nalopen, per eis een vinkje en een opmerking. Geen poort: de casus
 * gaat ook door als niet alles af is. De casus bewaart wat het team invulde;
 * wie later opnieuw afrondt, begint daarmee. Annuleren laat de fase staan.
 *
 * Staat de casus in de koelkast, dan haalt dezelfde wijziging hem eruit:
 * één call, zodat hij nooit uit de koelkast is zonder de nieuwe fase.
 * Annuleren laat hem in de koelkast.
 */
export function CasusAfrondenModal({ casus, fase, onClose }: Props) {
  if (!casus || !fase) return null;
  return <Formulier key={casus.id} casus={casus} fase={fase} onClose={onClose} />;
}

function Formulier({ casus, fase, onClose }: { casus: Casus; fase: { id: string; naam: string }; onClose: () => void }) {
  const update = useUpdateCasus();
  const soorten = casus.soorten ?? [];
  const [waarden, setWaarden] = useState<EisWaarden>(() => uitMomentopname(casus.eind_eisen));

  const afronden = async () => {
    try {
      await update.mutateAsync({
        id: casus.id,
        data: {
          fase: fase.id,
          eind_eisen: naarSoortEisen(soorten, 'eind_eisen', waarden),
          ...(casus.koelkast_sinds ? { uit_koelkast: true } : {}),
        },
      });
      onClose();
    } catch {
      // de melding is al getoond; het venster blijft open
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Naar ${fase.naam}: ${casus.title}`}
      entityLabel="Casus"
      size="md"
      closeable={!update.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onClose} text="Annuleren" disabled={update.isPending} />
          <NlddButton onClick={() => void afronden()} loading={update.isPending} text={`Naar ${fase.naam}`} />
        </>
      }
    >
      <nldd-container gap="16">
        <nldd-text size="sm" color="secondary">
          Loop de deliverables van de soorten van deze casus na. Vink aan wat af is en licht toe waar dat helpt. De
          casus gaat ook door als niet alles af is.
          {casus.koelkast_sinds ? ' Hij gaat daarmee ook uit de koelkast.' : ''}
        </nldd-text>
        <EisenNalopen
          soorten={soorten}
          lijst="eind_eisen"
          waarden={waarden}
          onChange={(k, deel) => setWaarden((w) => zetEis(w, k, deel))}
        />
      </nldd-container>
    </Modal>
  );
}
