import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

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
  /** Volgnummer in de rij; ook de key van het venster, zodat elke vraag leeg begint. */
  nr: number;
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
 *
 * De vragen staan in een rij. Sleep je twee taken zonder eigenaar snel achter
 * elkaar, dan komt de tweede vraag zodra de eerste klaar is, en draait elke
 * `daarna` op zijn beurt. Opent zo'n `daarna` zelf een venster (de DoD),
 * terwijl er nog een vraag wacht, dan staan die twee wel even op elkaar.
 */
export function OpNaamProvider({ children }: { children: ReactNode }) {
  const [rij, setRij] = useState<Vraag[]>([]);
  const volgnummer = useRef(0);

  const vraagOpNaam = useCallback<VraagOpNaam>((taak, status, initiatiefId, daarna) => {
    if (!vraagtEigenaar(status) || taak.assignee_id) {
      daarna?.();
      return;
    }
    volgnummer.current += 1;
    const nr = volgnummer.current;
    setRij((prev) => [...prev, { nr, taak, status, initiatiefId: initiatiefId ?? null, daarna }]);
  }, []);

  const vraag = rij[0];
  // Het laatst afgehandelde nummer. Sluiten kan twee keer binnenkomen (de
  // sluitknop en het close-event van het venster); `daarna` draait één keer.
  const afgehandeld = useRef(0);
  const klaar = () => {
    if (!vraag || afgehandeld.current >= vraag.nr) return;
    afgehandeld.current = vraag.nr;
    setRij((prev) => prev.filter((v) => v.nr !== vraag.nr));
    vraag.daarna?.();
  };

  return (
    <OpNaamContext.Provider value={vraagOpNaam}>
      {children}
      {vraag && <OpNaamVenster key={vraag.nr} vraag={vraag} onKlaar={klaar} />}
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
  // Iemand anders kies je in de lijst; jezelf zet je er met één knop op.
  const [keuze, setKeuze] = useState('');
  // Welke knop je indrukte: die draait, de andere niet.
  const [bezig, setBezig] = useState<'keuze' | 'ik' | null>(null);
  const ikKiesbaar = !!currentPerson && personOptions.some((o) => o.value === currentPerson.id);
  const af = status === TaskStatus.DONE;

  const opNaam = async (wie: string, knop: 'keuze' | 'ik') => {
    if (!wie) return;
    setBezig(knop);
    try {
      await update.mutateAsync({ id: taak.id, data: { assignee_id: wie } });
      onKlaar();
    } catch {
      // de melding is al getoond; het venster blijft open
      setBezig(null);
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
            onClick={() => void opNaam(keuze, 'keuze')}
            disabled={!keuze || (update.isPending && bezig !== 'keuze')}
            loading={update.isPending && bezig === 'keuze'}
            text="Op naam zetten"
          />
          {ikKiesbaar && (
            <NlddButton
              onClick={() => void opNaam(currentPerson.id, 'ik')}
              disabled={update.isPending && bezig !== 'ik'}
              loading={update.isPending && bezig === 'ik'}
              text="Op mijn naam"
            />
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
