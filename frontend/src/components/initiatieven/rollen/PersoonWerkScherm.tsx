import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Badge } from '@/components/common/Badge';
import { DetailSection } from '@/components/common/DetailSection';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddListItemButton } from '@/components/nldd/NlddLink';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { usePersoonWerk, useZetPersoonFocus } from '@/hooks/useInitiatiefRollen';
import {
  ISSUE_STATUS_COLORS,
  ISSUE_STATUS_LABELS,
  LEAD_STAGE_LABELS,
  TASK_STATUS_LABELS,
  issueSoortLabel,
} from '@/types';
import type { InitiatiefDetail } from '@/types';
import { formatDateShort } from '@/utils/dates';
import { initiatiefPath } from '@/utils/initiatiefRoutes';
import { EisenLijst } from '../EisenLijst';

const LEAD_ALS_LABELS: Record<string, string> = { eigenaar: 'Eigenaar', aanbrenger: 'Aanbrenger' };
const CASUS_ROL_LABELS: Record<string, string> = { trekker: 'Trekker', teamlid: 'Teamlid' };

/**
 * Wat één persoon binnen dit initiatief draagt: focus, rollen, interesse in
 * open rollen, leads, casussen, open onderzoeksvragen en issues, en open
 * taken. Alleen werk uit dit initiatief; elke regel opent het werk zelf, een
 * rol in het zijpaneel.
 */
export function PersoonWerkScherm({
  initiatief,
  personId,
  canEdit,
  onTerug,
  onKiesRol,
}: {
  initiatief: InitiatiefDetail;
  personId: string;
  canEdit: boolean;
  onTerug: () => void;
  onKiesRol: (rolId: string) => void;
}) {
  const { data: werk, isLoading, isError } = usePersoonWerk(initiatief.id, personId);
  const navigate = useNavigate();
  const { openLeadDetail } = useLeadDetail();
  const { openTaskDetail } = useTaskDetail();
  const naarCasus = (casusId: string) =>
    navigate(`${initiatiefPath(initiatief.id, 'casussen')}?casus=${encodeURIComponent(casusId)}`);
  const rollenAan = !!initiatief.rollen_enabled;

  const terug = (
    <div>
      <NlddButton variant="neutral-transparent" size="sm" startIcon="arrow-left" onClick={onTerug} text="Alle rollen" />
    </div>
  );

  if (isLoading) {
    return (
      <nldd-container gap="16">
        {terug}
        <nldd-container layout="row" horizontal-alignment="center" padding="48">
          <LoadingSpinner />
        </nldd-container>
      </nldd-container>
    );
  }
  if (isError || !werk) {
    return (
      <nldd-container gap="16">
        {terug}
        <nldd-text size="sm" color="secondary">Deze persoon is niet gevonden.</nldd-text>
      </nldd-container>
    );
  }

  return (
    <nldd-container gap="20">
      {terug}
      <nldd-container gap="4">
        <nldd-title size={3}>{werk.person.naam}</nldd-title>
        {!werk.is_lid && (
          <div>
            <Badge color="rood">Kan dit initiatief niet meer zien</Badge>
          </div>
        )}
      </nldd-container>

      <Focus
        key={werk.focus.join('|')}
        initiatiefId={initiatief.id}
        personId={personId}
        focus={werk.focus}
        canEdit={canEdit && werk.is_lid}
      />

      {rollenAan && (
        <DetailSection title="Rollen" count={werk.rollen.length}>
          {werk.rollen.length === 0 ? (
            <Leeg tekst="Geen rol." />
          ) : (
            <Lijst label="Rollen">
              {werk.rollen.map((r) => (
                <NlddListItemButton key={r.id} onClick={() => onKiesRol(r.id)}>
                  <nldd-text-cell text={r.naam} supporting-text={r.doel || undefined} width="full" />
                </NlddListItemButton>
              ))}
            </Lijst>
          )}
        </DetailSection>
      )}

      {rollenAan && werk.interesse.length > 0 && (
        <DetailSection title="Interesse in open rollen" count={werk.interesse.length}>
          <Lijst label="Interesse in open rollen">
            {werk.interesse.map((i) => (
              <NlddListItemButton key={i.rol_id} onClick={() => onKiesRol(i.rol_id)}>
                <Regel tekst={i.rol_naam} onder={i.invulling}>
                  <Badge color="oranje">Open</Badge>
                </Regel>
              </NlddListItemButton>
            ))}
          </Lijst>
        </DetailSection>
      )}

      <DetailSection title="Leads" count={werk.leads.length}>
        {werk.leads.length === 0 ? (
          <Leeg tekst="Geen leads." />
        ) : (
          <Lijst label="Leads">
            {werk.leads.map((l) => (
              <NlddListItemButton key={l.id} onClick={() => openLeadDetail(l.id)}>
                <Regel tekst={l.title} onder={LEAD_STAGE_LABELS[l.stage] ?? l.stage}>
                  {l.als.map((a) => (
                    <Badge key={a} color="coolgray">{LEAD_ALS_LABELS[a] ?? a}</Badge>
                  ))}
                </Regel>
              </NlddListItemButton>
            ))}
          </Lijst>
        )}
      </DetailSection>

      {initiatief.casussen_enabled && (
        <>
          <DetailSection title="Casussen" count={werk.casussen.length}>
            {werk.casussen.length === 0 ? (
              <Leeg tekst="Geen casussen." />
            ) : (
              <Lijst label="Casussen">
                {werk.casussen.map((c) => (
                  <NlddListItemButton key={c.id} onClick={() => naarCasus(c.id)}>
                    <Regel tekst={c.title} onder={faseNaam(initiatief, c.fase)}>
                      <Badge color={c.rol === 'trekker' ? 'paars' : 'coolgray'}>{CASUS_ROL_LABELS[c.rol] ?? c.rol}</Badge>
                    </Regel>
                  </NlddListItemButton>
                ))}
              </Lijst>
            )}
          </DetailSection>

          <DetailSection title="Open onderzoeksvragen en issues" count={werk.issues.length}>
            {werk.issues.length === 0 ? (
              <Leeg tekst="Geen open onderzoeksvragen of issues." />
            ) : (
              <Lijst label="Open onderzoeksvragen en issues">
                {werk.issues.map((i) => (
                  <NlddListItemButton
                    key={i.id}
                    onClick={() => (i.casus_id ? naarCasus(i.casus_id) : navigate(initiatiefPath(initiatief.id, 'backlog')))}
                  >
                    <Regel tekst={i.title} onder={[issueSoortLabel(i), i.casus_title ?? 'zonder casus'].join(' · ')}>
                      <Badge color={ISSUE_STATUS_COLORS[i.status]}>{ISSUE_STATUS_LABELS[i.status]}</Badge>
                    </Regel>
                  </NlddListItemButton>
                ))}
              </Lijst>
            )}
          </DetailSection>

          <DetailSection title="Open taken" count={werk.open_taken.length}>
            {werk.open_taken.length === 0 ? (
              <Leeg tekst="Geen open taken." />
            ) : (
              <Lijst label="Open taken">
                {werk.open_taken.map((t) => (
                  <NlddListItemButton key={t.id} onClick={() => openTaskDetail(t.id)}>
                    <Regel
                      tekst={t.title}
                      onder={[t.casus_title, t.deadline ? `deadline ${formatDateShort(t.deadline)}` : null]
                        .filter(Boolean)
                        .join(' · ')}
                    >
                      <Badge color="coolgray">{TASK_STATUS_LABELS[t.status]}</Badge>
                    </Regel>
                  </NlddListItemButton>
                ))}
              </Lijst>
            )}
          </DetailSection>
        </>
      )}
    </nldd-container>
  );
}

function faseNaam(initiatief: InitiatiefDetail, fase: string): string {
  return initiatief.casus_fases?.find((f) => f.id === fase)?.naam ?? fase;
}

function Lijst({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <nldd-list type="list" appearance="box-tinted" accessible-label={label}>
      {children}
    </nldd-list>
  );
}

function Regel({ tekst, onder, children }: { tekst: string; onder?: string | null; children?: React.ReactNode }) {
  return (
    <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
      <nldd-text-cell text={tekst} supporting-text={onder || undefined} width="full" />
      {children && <div className="hug">{children}</div>}
    </nldd-container>
  );
}

function Leeg({ tekst }: { tekst: string }) {
  return <nldd-text size="sm" color="secondary">{tekst}</nldd-text>;
}

/** De persoonlijke focus: een paar vrije regels, door het team bij te werken. */
function Focus({
  initiatiefId,
  personId,
  focus,
  canEdit,
}: {
  initiatiefId: string;
  personId: string;
  focus: string[];
  canEdit: boolean;
}) {
  const zet = useZetPersoonFocus();
  const [bewerken, setBewerken] = useState(false);
  const [regels, setRegels] = useState(focus);

  const opslaan = async () => {
    try {
      await zet.mutateAsync({ initiatiefId, personId, focus: regels.map((r) => r.trim()).filter(Boolean) });
      setBewerken(false);
    } catch {
      // de melding is al getoond
    }
  };

  return (
    <DetailSection
      title="Focus"
      count={focus.length}
      action={
        canEdit && !bewerken ? (
          <NlddButton variant="neutral-transparent" size="sm" startIcon="pencil" onClick={() => setBewerken(true)} text="Bewerken" />
        ) : undefined
      }
    >
      {bewerken ? (
        <nldd-container gap="8">
          <EisenLijst
            items={regels}
            onChange={setRegels}
            naam="Focuspunt"
            placeholder="Bijvoorbeeld: Napp naar productie"
            leeg="Nog geen focus. Voeg hieronder een punt toe."
            nieuwLabel="Nieuw focuspunt"
            max={20}
          />
          <nldd-container layout="row" gap="8">
            <NlddButton
              variant="secondary"
              size="sm"
              onClick={() => {
                setRegels(focus);
                setBewerken(false);
              }}
              text="Annuleren"
            />
            <NlddButton size="sm" onClick={() => void opslaan()} loading={zet.isPending} text="Opslaan" />
          </nldd-container>
        </nldd-container>
      ) : focus.length === 0 ? (
        <Leeg tekst="Nog geen focus." />
      ) : (
        <nldd-rich-text>
          <ul>
            {focus.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </nldd-rich-text>
      )}
    </DetailSection>
  );
}
