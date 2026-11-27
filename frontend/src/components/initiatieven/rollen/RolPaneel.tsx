import { useMemo, useState } from 'react';

import { Badge } from '@/components/common/Badge';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DetailSection } from '@/components/common/DetailSection';
import { Input } from '@/components/common/Input';
import { Modal } from '@/components/common/Modal';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Select } from '@/components/common/Select';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { NlddActionText } from '@/components/nldd/NlddLink';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useInitiatiefPersonen } from '@/hooks/useInitiatieven';
import {
  useCreateRol,
  useDeleteRol,
  useMaakRaakvlak,
  useUpdateRol,
  useVerwijderInteresse,
  useVerwijderRaakvlak,
  useZetInteresse,
} from '@/hooks/useInitiatiefRollen';
import { ROL_STATUS_LABELS } from '@/types';
import type { EntityColor, InitiatiefDetail, InitiatiefRol, RolInteresse } from '@/types';
import { richTextToPlain } from '@/utils/richtext';
import { EisenLijst } from '../EisenLijst';
import { isBelegd } from './rollenFilter';

interface Props {
  initiatief: InitiatiefDetail;
  rollen: InitiatiefRol[];
  rol: InitiatiefRol | null;
  nieuw: boolean;
  canEdit: boolean;
  onClose: () => void;
  onKiesRol: (rolId: string) => void;
}

const STATUS_KLEUR: Record<InitiatiefRol['status'], EntityColor> = {
  concept: 'coolgray',
  open: 'oranje',
  belegd: 'paars',
};

/**
 * Eén rol in een zijpaneel rechts, vanuit de cirkel, de lijst en de
 * persoonspagina. Het toewijzen volgt de status: concept, bekend maken
 * (open, interesse peilen), toewijzen (belegd), en opnieuw toewijzen terug
 * naar open met een nieuwe ronde interesse.
 */
export function RolPaneel({ initiatief, rollen, rol, nieuw, canEdit, onClose, onKiesRol }: Props) {
  const [bewerken, setBewerken] = useState(false);
  if (nieuw) {
    return <RolFormulier key="nieuw" initiatief={initiatief} rol={null} onKlaar={onClose} onAangemaakt={onKiesRol} />;
  }
  if (!rol) return null;
  if (bewerken) {
    return (
      <RolFormulier
        key={rol.id}
        initiatief={initiatief}
        rol={rol}
        onKlaar={() => setBewerken(false)}
        onVerwijderd={() => {
          setBewerken(false);
          onClose();
        }}
      />
    );
  }
  return (
    <Modal
      open
      onClose={onClose}
      title={rol.naam}
      entityLabel="Rol"
      size="lg"
      placement="right"
      dismissText="Sluit"
      toolbar={
        canEdit ? (
          <NlddButton variant="neutral-transparent" size="sm" startIcon="pencil" onClick={() => setBewerken(true)} text="Bewerken" />
        ) : undefined
      }
    >
      <RolDetail
        key={rol.id}
        initiatief={initiatief}
        rollen={rollen}
        rol={rol}
        canEdit={canEdit}
        onKiesRol={onKiesRol}
      />
    </Modal>
  );
}

function useTeam(initiatiefId: string) {
  const { data: personen } = useInitiatiefPersonen(initiatiefId);
  return useMemo(() => (personen ?? []).filter((p) => !p.is_agent), [personen]);
}

function RolDetail({
  initiatief,
  rollen,
  rol,
  canEdit,
  onKiesRol,
}: {
  initiatief: InitiatiefDetail;
  rollen: InitiatiefRol[];
  rol: InitiatiefRol;
  canEdit: boolean;
  onKiesRol: (rolId: string) => void;
}) {
  return (
    <nldd-container gap="20">
      <Toewijzing key={`${rol.id}-${rol.ronde}-${rol.status}`} initiatiefId={initiatief.id} rol={rol} canEdit={canEdit} />
      <DetailSection title="Doel">
        <nldd-text size="sm">{rol.doel || 'Nog geen doel.'}</nldd-text>
      </DetailSection>
      <DetailSection title="Domein" count={rol.domein.length}>
        <Regels regels={rol.domein} leeg="Geen domein." />
      </DetailSection>
      <DetailSection title="Aanspreekbaar op" count={rol.aanspreekbaar_op.length}>
        <Regels regels={rol.aanspreekbaar_op} leeg="Nog niets vastgelegd." />
      </DetailSection>
      <DetailSection title="Raakvlakken" count={rol.raakvlakken.length}>
        <Raakvlakken initiatiefId={initiatief.id} rollen={rollen} rol={rol} canEdit={canEdit} onKiesRol={onKiesRol} />
      </DetailSection>
      {rol.status === 'open' && (
        <DetailSection title="Interesse" count={rol.interesse.length}>
          <Interesse initiatiefId={initiatief.id} rol={rol} canEdit={canEdit} />
        </DetailSection>
      )}
      {rol.toelichting && (
        <DetailSection title="Toelichting">
          <RichTextDisplay content={rol.toelichting} />
        </DetailSection>
      )}
      {rol.feedback && (
        <DetailSection title="Feedback op de rol">
          <RichTextDisplay content={rol.feedback} />
        </DetailSection>
      )}
      {rol.eerdere_interesse.length > 0 && <EerdereInteresse lijst={rol.eerdere_interesse} />}
    </nldd-container>
  );
}

/** Status, vervuller en de volgende stap in het toewijzen. */
function Toewijzing({ initiatiefId, rol, canEdit }: { initiatiefId: string; rol: InitiatiefRol; canEdit: boolean }) {
  const update = useUpdateRol();
  const team = useTeam(initiatiefId);
  // Wie interesse heeft, staat bovenaan de keuzelijst.
  const opties = useMemo(() => {
    const geinteresseerd = new Set(rol.interesse.map((i) => i.person.id));
    return [...team]
      .sort((a, b) => Number(geinteresseerd.has(b.id)) - Number(geinteresseerd.has(a.id)))
      .map((p) => ({ value: p.id, label: geinteresseerd.has(p.id) ? `${p.naam} (interesse)` : p.naam }));
  }, [team, rol.interesse]);
  const [kandidaat, setKandidaat] = useState(rol.interesse[0]?.person.id ?? '');
  const zet = (data: { status?: 'concept' | 'open'; vervuller_id?: string | null }) =>
    update.mutate({ initiatiefId, rolId: rol.id, data });

  return (
    <nldd-container gap="8">
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <Badge color={STATUS_KLEUR[rol.status]}>{ROL_STATUS_LABELS[rol.status]}</Badge>
        {rol.status === 'belegd' && rol.vervuller && <nldd-text size="sm">{rol.vervuller.naam}</nldd-text>}
        {rol.vervuller && !rol.vervuller_is_lid && <Badge color="rood">Kan dit initiatief niet meer zien</Badge>}
      </nldd-container>
      {rol.status === 'belegd' && !isBelegd(rol) && (
        <nldd-text size="xs" color="secondary">
          {rol.vervuller ? 'De vervuller kan dit initiatief niet meer zien.' : 'De vervuller bestaat niet meer.'} Wijs
          de rol opnieuw toe om interesse te peilen.
        </nldd-text>
      )}
      {rol.status === 'concept' && (
        <nldd-text size="xs" color="secondary">
          Een concept: het team ziet hem al, maar er wordt nog niemand voor gezocht.
        </nldd-text>
      )}
      {canEdit && rol.status === 'concept' && (
        <div>
          <NlddButton size="sm" startIcon="megaphone" onClick={() => zet({ status: 'open' })} loading={update.isPending} text="Bekend maken" />
        </div>
      )}
      {canEdit && rol.status === 'open' && (
        <nldd-container layout="wrap" gap="8" vertical-alignment="bottom">
          <Select
            label="Toewijzen aan"
            required
            value={kandidaat}
            onChange={(e) => setKandidaat(e.target.value)}
            options={opties}
            placeholder="Kies iemand uit het team"
            size="sm"
            width="260px"
          />
          <NlddButton
            size="sm"
            onClick={() => kandidaat && zet({ vervuller_id: kandidaat })}
            disabled={!kandidaat}
            loading={update.isPending}
            text="Toewijzen"
          />
          <NlddButton variant="neutral-transparent" size="sm" onClick={() => zet({ status: 'concept' })} text="Terug naar concept" />
        </nldd-container>
      )}
      {canEdit && rol.status === 'belegd' && (
        <div>
          <NlddButton
            variant="secondary"
            size="sm"
            startIcon="arrow-2-counter-clockwise"
            onClick={() => zet({ status: 'open' })}
            loading={update.isPending}
            text="Opnieuw toewijzen"
          />
        </div>
      )}
    </nldd-container>
  );
}

function Regels({ regels, leeg }: { regels: string[]; leeg: string }) {
  if (regels.length === 0) return <nldd-text size="sm" color="secondary">{leeg}</nldd-text>;
  return (
    <nldd-rich-text>
      <ul>
        {regels.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </nldd-rich-text>
  );
}

/** Raakvlakken met andere rollen; een rol hier opent die rol. */
function Raakvlakken({
  initiatiefId,
  rollen,
  rol,
  canEdit,
  onKiesRol,
}: {
  initiatiefId: string;
  rollen: InitiatiefRol[];
  rol: InitiatiefRol;
  canEdit: boolean;
  onKiesRol: (rolId: string) => void;
}) {
  const maak = useMaakRaakvlak();
  const weg = useVerwijderRaakvlak();
  const [ander, setAnder] = useState('');
  const [omschrijving, setOmschrijving] = useState('');
  const bezet = new Set([rol.id, ...rol.raakvlakken.map((rv) => rv.rol.id)]);
  const opties = rollen.filter((r) => !bezet.has(r.id)).map((r) => ({ value: r.id, label: r.naam }));

  const toevoegen = async () => {
    if (!ander) return;
    try {
      await maak.mutateAsync({ initiatiefId, rolId: rol.id, anderRolId: ander, omschrijving: omschrijving.trim() || null });
      setAnder('');
      setOmschrijving('');
    } catch {
      // de melding is al getoond
    }
  };

  return (
    <nldd-container gap="8">
      {rol.raakvlakken.length === 0 ? (
        <nldd-text size="sm" color="secondary">Geen raakvlakken.</nldd-text>
      ) : (
        <nldd-list type="list" appearance="box-tinted" accessible-label="Raakvlakken">
          {rol.raakvlakken.map((rv) => (
            <nldd-list-item key={rv.id}>
            <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
              <nldd-container gap="2" width="full">
                <NlddActionText size="sm" text={rv.rol.naam} onClick={() => onKiesRol(rv.rol.id)} />
                {rv.omschrijving && <nldd-text size="xs" color="secondary">{rv.omschrijving}</nldd-text>}
              </nldd-container>
              {canEdit && (
                <NlddIconButton
                  icon="close"
                  accessibleLabel={`Raakvlak met ${rv.rol.naam} weghalen`}
                  variant="neutral-transparent"
                  size="sm"
                  onClick={() => weg.mutate({ initiatiefId, raakvlakId: rv.id })}
                />
              )}
            </nldd-container>
            </nldd-list-item>
          ))}
        </nldd-list>
      )}
      {canEdit && opties.length > 0 && (
        <nldd-container gap="8">
          <Select
            label="Raakvlak met"
            required
            value={ander}
            onChange={(e) => setAnder(e.target.value)}
            options={opties}
            placeholder="Kies een rol"
            size="sm"
            width="260px"
          />
          {ander && (
            <>
              <Input
                type="text"
                label="Waar gaat het over"
                value={omschrijving}
                maxLength={500}
                placeholder="Bijvoorbeeld: Aanspreekpunt geeft het belang, Spelverdeler de inzet"
                onChange={(e) => setOmschrijving(e.target.value)}
              />
              <div>
                <NlddButton variant="secondary" size="sm" onClick={() => void toevoegen()} loading={maak.isPending} text="Raakvlak toevoegen" />
              </div>
            </>
          )}
        </nldd-container>
      )}
    </nldd-container>
  );
}

/**
 * Interesse in een open rol. Standaard leg je het voor jezelf vast; wie
 * het in een gesprek of de retro hoorde, kiest "voor iemand anders".
 */
function Interesse({ initiatiefId, rol, canEdit }: { initiatiefId: string; rol: InitiatiefRol; canEdit: boolean }) {
  const team = useTeam(initiatiefId);
  const { currentPerson } = useCurrentPerson();
  const zelfInTeam = !!currentPerson && team.some((p) => p.id === currentPerson.id);
  const zet = useZetInteresse();
  const weg = useVerwijderInteresse();
  const [anders, setAnders] = useState(false);
  const [persoon, setPersoon] = useState('');
  const [invulling, setInvulling] = useState('');
  const voorWie = anders || !zelfInTeam ? persoon : currentPerson!.id;
  const alGedaan = rol.interesse.some((i) => i.person.id === voorWie);

  const vastleggen = async () => {
    if (!voorWie) return;
    try {
      await zet.mutateAsync({ initiatiefId, rolId: rol.id, personId: voorWie, invulling: invulling.trim() || null });
      setInvulling('');
      setPersoon('');
      setAnders(false);
    } catch {
      // de melding is al getoond
    }
  };

  return (
    <nldd-container gap="8">
      {rol.interesse.length === 0 ? (
        <nldd-text size="sm" color="secondary">Nog niemand.</nldd-text>
      ) : (
        <InteresseLijst
          lijst={rol.interesse}
          onWeg={canEdit ? (personId) => weg.mutate({ initiatiefId, rolId: rol.id, personId }) : undefined}
        />
      )}
      {canEdit && (
        <nldd-container gap="8">
          {anders || !zelfInTeam ? (
            <Select
              label="Voor wie"
            required
              value={persoon}
              onChange={(e) => setPersoon(e.target.value)}
              options={team.map((p) => ({ value: p.id, label: p.naam }))}
              placeholder="Kies iemand uit het team"
              size="sm"
              width="260px"
            />
          ) : (
            <nldd-container layout="row" gap="8" vertical-alignment="center">
              <nldd-text size="sm">Voor jou ({currentPerson!.naam})</nldd-text>
              <NlddActionText size="sm" text="voor iemand anders" onClick={() => setAnders(true)} />
            </nldd-container>
          )}
          <Input
            type="text"
            label="Hoe zie je het voor je"
            value={invulling}
            maxLength={2000}
            placeholder="Bijvoorbeeld: vanaf januari, twee dagen per week"
            onChange={(e) => setInvulling(e.target.value)}
          />
          <div>
            <NlddButton
              variant="secondary"
              size="sm"
              onClick={() => void vastleggen()}
              disabled={!voorWie}
              loading={zet.isPending}
              text={alGedaan ? 'Interesse bijwerken' : 'Interesse vastleggen'}
            />
          </div>
        </nldd-container>
      )}
    </nldd-container>
  );
}

function InteresseLijst({ lijst, onWeg }: { lijst: RolInteresse[]; onWeg?: (personId: string) => void }) {
  return (
    <nldd-list type="list" appearance="box-tinted" accessible-label="Interesse">
      {lijst.map((i) => (
        <nldd-list-item key={`${i.ronde}-${i.person.id}`}>
          <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
            <nldd-text-cell
              text={i.person.naam}
              supporting-text={
                [i.invulling, i.vastgelegd_door && i.vastgelegd_door.id !== i.person.id ? `vastgelegd door ${i.vastgelegd_door.naam}` : null]
                  .filter(Boolean)
                  .join(' · ') || undefined
              }
              width="full"
            />
            {onWeg && (
              <NlddIconButton
                icon="close"
                accessibleLabel={`Interesse van ${i.person.naam} weghalen`}
                variant="neutral-transparent"
                size="sm"
                onClick={() => onWeg(i.person.id)}
              />
            )}
          </nldd-container>
        </nldd-list-item>
      ))}
    </nldd-list>
  );
}

/** Interesse uit eerdere toewijzingsrondes: ingeklapt, voor als je wilt terugkijken. */
function EerdereInteresse({ lijst }: { lijst: RolInteresse[] }) {
  const [open, setOpen] = useState(false);
  return (
    <nldd-container gap="8">
      <NlddActionText
        size="sm"
        text={`${open ? 'Verberg' : 'Toon'} interesse bij eerdere toewijzing (${lijst.length})`}
        onClick={() => setOpen(!open)}
      />
      {open && <InteresseLijst lijst={lijst} />}
    </nldd-container>
  );
}

function RolFormulier({
  initiatief,
  rol,
  onKlaar,
  onAangemaakt,
  onVerwijderd,
}: {
  initiatief: InitiatiefDetail;
  rol: InitiatiefRol | null;
  onKlaar: () => void;
  onAangemaakt?: (rolId: string) => void;
  onVerwijderd?: () => void;
}) {
  const create = useCreateRol();
  const update = useUpdateRol();
  const del = useDeleteRol();
  const [naam, setNaam] = useState(rol?.naam ?? '');
  const [doel, setDoel] = useState(rol?.doel ?? '');
  const [aanspreekbaar, setAanspreekbaar] = useState<string[]>(rol?.aanspreekbaar_op ?? []);
  const [domein, setDomein] = useState<string[]>(rol?.domein ?? []);
  const [toelichting, setToelichting] = useState(rol?.toelichting ?? '');
  const [feedback, setFeedback] = useState(rol?.feedback ?? '');
  const [verwijderen, setVerwijderen] = useState(false);
  const bezig = create.isPending || update.isPending;
  const rijk = (v: string) => (richTextToPlain(v).trim() ? v : null);
  const schoon = (regels: string[]) => regels.map((r) => r.trim()).filter(Boolean);

  const opslaan = async () => {
    const data = {
      naam: naam.trim(),
      doel: doel.trim() || null,
      aanspreekbaar_op: schoon(aanspreekbaar),
      domein: schoon(domein),
      toelichting: rijk(toelichting),
      feedback: rijk(feedback),
    };
    try {
      if (rol) {
        await update.mutateAsync({ initiatiefId: initiatief.id, rolId: rol.id, data });
        onKlaar();
      } else {
        const nieuw = await create.mutateAsync({ initiatiefId: initiatief.id, data });
        onAangemaakt?.(nieuw.id);
      }
    } catch {
      // de melding is al getoond; het paneel blijft open
    }
  };

  return (
    <>
      <Modal
        open
        onClose={onKlaar}
        title={rol ? `${rol.naam} bewerken` : 'Nieuwe rol'}
        entityLabel="Rol"
        size="lg"
        placement="right"
        closeable={!bezig}
        footer={
          <>
            {rol && (
              <NlddButton
                variant="neutral-transparent"
                startIcon="trash"
                onClick={() => setVerwijderen(true)}
                text="Verwijderen"
                disabled={bezig}
              />
            )}
            <NlddButton variant="secondary" onClick={onKlaar} text="Annuleren" disabled={bezig} />
            <NlddButton onClick={() => void opslaan()} loading={bezig} disabled={!naam.trim()} text="Opslaan" />
          </>
        }
      >
        <nldd-container gap="20">
          {!rol && (
            <nldd-text size="xs" color="secondary">
              Een nieuwe rol begint als concept. Bekend maken en toewijzen doe je daarna in het paneel.
            </nldd-text>
          )}
          <Input
            type="text"
            label="Naam"
            value={naam}
            maxLength={150}
            required
            placeholder="Bijvoorbeeld: Spelverdeler"
            onChange={(e) => setNaam(e.target.value)}
          />
          <Input
            type="text"
            label="Doel"
            value={doel}
            maxLength={2000}
            placeholder="Waarom dit werk bestaat: wat het wil bereiken"
            onChange={(e) => setDoel(e.target.value)}
          />
          <nldd-container gap="8">
            <nldd-container gap="2">
              <nldd-text size="sm" weight="bold">Aanspreekbaar op</nldd-text>
              <nldd-text size="xs" color="secondary">
                Wat anderen blijvend mogen verwachten. Schrijf als resultaat: &quot;Dat er ... is&quot;.
              </nldd-text>
            </nldd-container>
            <EisenLijst
              items={aanspreekbaar}
              onChange={setAanspreekbaar}
              naam="Punt"
              placeholder="Bijvoorbeeld: dat de vaste rituelen zijn ingepland"
              leeg="Nog niets. Voeg hieronder een punt toe."
              nieuwLabel="Nieuw punt"
            />
          </nldd-container>
          <nldd-container gap="8">
            <nldd-container gap="2">
              <nldd-text size="sm" weight="bold">Domein</nldd-text>
              <nldd-text size="xs" color="secondary">
                Waar de rol over gaat. Wil een ander daar iets veranderen, dan consulteert die eerst deze rol.
              </nldd-text>
            </nldd-container>
            <EisenLijst
              items={domein}
              onChange={setDomein}
              naam="Domein"
              placeholder="Bijvoorbeeld: de teamagenda"
              leeg="Geen domein. Voeg hieronder een toe."
              nieuwLabel="Nieuw domein"
            />
          </nldd-container>
          <RichTextFormField hideOptional label="Toelichting" value={toelichting} onChange={setToelichting} rows={3} />
          <RichTextFormField
            hideOptional
            label="Feedback op de rol"
            value={feedback}
            onChange={setFeedback}
            rows={3}
            placeholder="Bijvoorbeeld: opsplitsen, of samenvoegen met een andere rol"
          />
        </nldd-container>
      </Modal>
      {rol && (
        <ConfirmDialog
          open={verwijderen}
          onClose={() => setVerwijderen(false)}
          onConfirm={async () => {
            try {
              await del.mutateAsync({ initiatiefId: initiatief.id, rolId: rol.id });
              setVerwijderen(false);
              onVerwijderd?.();
            } catch {
              // de melding is al getoond
            }
          }}
          title="Rol verwijderen"
          confirmLabel="Verwijderen"
          variant="danger"
          loading={del.isPending}
        >
          {`"${rol.naam}" verdwijnt, met de interesse en de raakvlakken.`}
        </ConfirmDialog>
      )}
    </>
  );
}
