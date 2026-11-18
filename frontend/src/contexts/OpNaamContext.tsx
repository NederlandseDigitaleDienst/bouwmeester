import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

import { Modal } from '@/components/common/Modal';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useInitiatiefPersonOptions } from '@/hooks/useInitiatiefPersonOptions';
import { useUpdateTask } from '@/hooks/useTasks';
import { TaskStatus, type TaskCasusSummary } from '@/types';

/** Statussen waarbij er kennelijk iemand aan werkt of het gedaan heeft. */
const MET_IEMAND: ReadonlySet<TaskStatus> = new Set([TaskStatus.IN_PROGRESS, TaskStatus.DONE]);

/** Hoort er bij deze status iemand op de taak te staan? */
export function vraagtEigenaar(status: TaskStatus): boolean {
  return MET_IEMAND.has(status);
}

interface Taak {
  id: string;
  title: string;
  assignee_id?: string | null;
  /** De casus van de taak; daar komt het initiatief vandaan als het niet is meegegeven. */
  casus?: Partial<TaskCasusSummary> | null;
}

interface Vraag {
  taak: Taak;
  status: TaskStatus;
  initiatiefId: string | null;
  daarna?: () => void;
}

type VraagOpNaam = (
  taak: Taak,
  status: TaskStatus,
  /**
   * Bij werk (een taak in een casus of onder een vraag): alleen leden van
   * dit initiatief zijn te kiezen. Leeg: het initiatief van de casus van
   * de taak.
   */
  initiatiefId?: string | null,
  /** Draait als de vraag klaar is (op naam gezet of overgeslagen), of meteen als er niets te vragen valt. */
  daarna?: () => void,
) => void;

/** Zonder provider (tests, de publieke pagina) valt er niets te vragen. */
const OpNaamContext = createContext<VraagOpNaam>((_taak, _status, _init, daarna) => daarna?.());

/**
 * Gaat een taak zonder eigenaar naar In uitvoering of Afgerond, dan vraagt
 * een klein venster of je hem op naam wilt zetten, met een keuzelijst. Dat is
 * niet verplicht: Niet nu laat de taak zonder naam.
 *
 * Eén venster voor de hele app, hier in de provider: een taakkaartje dat van
 * kolom wisselt wordt opnieuw opgebouwd, en een venster in het kaartje zelf
 * zou dan verdwijnen.
 *
 * Roep de vraag aan nadat de nieuwe status is opgeslagen, met de taak zoals
 * hij was (dus met de oude eigenaar). `daarna` is voor wat erna moet, zoals
 * de DoD-checklist als de laatste taak af is: zo komen er geen twee vensters
 * tegelijk.
 */
export function OpNaamProvider({ children }: { children: ReactNode }) {
  const [vraag, setVraag] = useState<Vraag | null>(null);

  const vraagOpNaam = useCallback<VraagOpNaam>((taak, status, initiatiefId, daarna) => {
    if (!vraagtEigenaar(status) || taak.assignee_id) {
      daarna?.();
      return;
    }
    setVraag({ taak, status, initiatiefId: initiatiefId ?? null, daarna });
  }, []);

  const klaar = () => {
    const daarna = vraag?.daarna;
    setVraag(null);
    daarna?.();
  };

  return (
    <OpNaamContext.Provider value={vraagOpNaam}>
      {children}
      {vraag && <OpNaamVenster key={`${vraag.taak.id}-${vraag.status}`} vraag={vraag} onKlaar={klaar} />}
    </OpNaamContext.Provider>
  );
}

export function useOpNaam(): VraagOpNaam {
  return useContext(OpNaamContext);
}

function OpNaamVenster({ vraag, onKlaar }: { vraag: Vraag; onKlaar: () => void }) {
  const { taak, status } = vraag;
  // Meestal geeft de aanroeper het initiatief mee; anders komt het van de
  // casus van de taak. Zonder beide is iedereen te kiezen.
  const initiatiefId = vraag.initiatiefId ?? taak.casus?.initiatief_id ?? null;
  const update = useUpdateTask();
  const { currentPerson } = useCurrentPerson();
  const personOptions = useInitiatiefPersonOptions(null, initiatiefId);
  // Iemand anders kies je in de lijst; jezelf koppel je met één knop.
  const [keuze, setKeuze] = useState('');
  const ikKiesbaar = !!currentPerson && personOptions.some((o) => o.value === currentPerson.id);
  const af = status === TaskStatus.DONE;

  const opNaam = async (wie: string) => {
    if (!wie) return;
    try {
      await update.mutateAsync({ id: taak.id, data: { assignee_id: wie } });
      onKlaar();
    } catch {
      // de melding is al getoond; het venster blijft open
    }
  };

  return (
    <Modal
      open
      onClose={onKlaar}
      title="Op naam zetten?"
      size="sm"
      closeable={!update.isPending}
      footer={
        <>
          <NlddButton variant="secondary" onClick={onKlaar} text="Niet nu" disabled={update.isPending} />
          <NlddButton
            variant={ikKiesbaar ? 'secondary' : undefined}
            onClick={() => void opNaam(keuze)}
            disabled={!keuze || update.isPending}
            text="Op naam zetten"
          />
          {ikKiesbaar && (
            <NlddButton onClick={() => void opNaam(currentPerson.id)} loading={update.isPending} text="Aan mij koppelen" />
          )}
        </>
      }
    >
      <nldd-container gap="16">
        <nldd-text size="sm">
          {`"${taak.title}" ${af ? 'is afgerond' : 'staat nu in uitvoering'}, maar nog niet op naam. ${af ? 'Wie heeft hem gedaan?' : 'Wie doet hem?'}`}
        </nldd-text>
        {/* Opnieuw tekenen zodra de namen binnen zijn: de dropdown ververst
            zijn label niet als alleen de opties veranderen. */}
        <Select
          key={personOptions.length}
          compact
          label="Op naam van"
          width="240px"
          options={[{ value: '', label: 'Kies iemand' }, ...personOptions.filter((o) => o.value)]}
          value={keuze}
          onChange={(e) => setKeuze(e.target.value)}
        />
      </nldd-container>
    </Modal>
  );
}
