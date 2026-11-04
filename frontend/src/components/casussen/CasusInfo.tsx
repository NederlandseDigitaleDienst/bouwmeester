import { useState } from 'react';

import { Select } from '@/components/common/Select';
import { DetailSection } from '@/components/common/DetailSection';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { Icon } from '@/components/nldd/Icon';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { useRemoveCasusTeamlid, useUpdateCasus } from '@/hooks/useCasussen';
import { CASUS_TYPE_LABELS, CASUSTEAM_ROL_LABELS } from '@/types';
import { useCasusFases } from '@/hooks/useCasusFases';
import type { CasusDetail } from '@/types';
import { CasusTeamModal } from './CasusTeamModal';
import { antwoordTekst } from './startvragen';
import { CasusSoortenKiezer } from './CasusSoorten';
import { CasusAfrondenModal } from './CasusAfrondenModal';
import { EisenMomentopname } from './EisenNalopen';
import { heeftEisen } from './eisen';
import { useCasusSoorten, useZetCasusSoorten } from '@/hooks/useCasusSoorten';

/**
 * De gegevens van een casus naast het werk: fase, team, startvoorwaarden en
 * herkomst. Staat inline in het casusoverzicht, uitklapbaar; geen eigen
 * venster, want taakdetail en issue bewerken openen al een venster.
 */
export function CasusInfo({ casus }: { casus: CasusDetail }) {
  const updateCasus = useUpdateCasus();
  // De fases uit de casusfunnel van het initiatief (instellingen).
  const fases = useCasusFases(casus.initiatief_id ?? null);
  const faseIndex = fases.findIndex((f) => f.id === casus.fase);
  const huidige = faseIndex >= 0 ? fases[faseIndex] : undefined;
  const faseOptions = fases.length
    ? fases.map((f) => ({ value: f.id, label: f.naam }))
    : [{ value: casus.fase, label: casus.fase }];
  const { data: alleSoorten } = useCasusSoorten(casus.initiatief_id ?? null);
  const zetSoorten = useZetCasusSoorten();
  const removeTeamlid = useRemoveCasusTeamlid();
  const { openLeadDetail } = useLeadDetail();
  const [showTeam, setShowTeam] = useState(false);
  const sv = casus.startvoorwaarden ?? {};
  // Naar de laatste fase met eindeisen: eerst nalopen. Annuleren zet de
  // keuzelijst terug op de fase die de casus heeft (opnieuw mounten).
  const laatste = fases.length ? fases[fases.length - 1] : undefined;
  const [afronden, setAfronden] = useState(false);
  const [herstel, setHerstel] = useState(0);
  const eindEisen = casus.eind_eisen ?? [];

  return (
    <nldd-container gap="16">
      <nldd-container gap="6">
        <Select
          key={`${fases.length ? 'fases' : 'laden'}-${herstel}`}
          compact
          label="Fase"
          size="sm"
          width="220px"
          options={faseOptions}
          value={casus.fase}
          onChange={(e) => {
            const fase = e.target.value;
            if (fase === laatste?.id && heeftEisen(casus.soorten ?? [], 'eind_eisen')) setAfronden(true);
            else updateCasus.mutate({ id: casus.id, data: { fase } });
          }}
        />
        <CasusAfrondenModal
          casus={afronden ? casus : null}
          fase={laatste ?? null}
          onClose={() => {
            setAfronden(false);
            setHerstel((h) => h + 1);
          }}
        />
        {/* Wat er in deze fase gebeurt en wanneer de casus door mag. */}
        {huidige?.omschrijving && <nldd-text size="sm" color="secondary">{huidige.omschrijving}</nldd-text>}
        {huidige?.door_als && (
          <nldd-text size="sm" color="secondary">
            <strong>{faseIndex === fases.length - 1 ? 'Klaar als' : 'Door als'}:</strong> {huidige.door_als}
          </nldd-text>
        )}
      </nldd-container>

      {casus.description && <RichTextDisplay content={casus.description} />}

      <DetailSection title="Soorten" icon={<Icon name="tag" size="sm" />} count={casus.soorten?.length ?? 0} separated>
        {/* Meteen opgeslagen per vinkje. Alleen soorten van het eigen initiatief. */}
        <CasusSoortenKiezer
          soorten={alleSoorten ?? []}
          gekozen={(casus.soorten ?? []).map((s) => s.id)}
          onChange={(ids) => zetSoorten.mutate({ casusId: casus.id, soortIds: ids })}
        />
      </DetailSection>

      <DetailSection
        title="Casusteam"
        icon={<Icon name="users" size="sm" />}
        count={casus.team.length}
        separated
        action={
          <NlddButton variant="neutral-transparent" size="sm" startIcon="plus" onClick={() => setShowTeam(true)} text="Toevoegen" />
        }
      >
        {casus.team.length > 0 ? (
          <nldd-list appearance="simple" dividers="never" accessible-label="Casusteam">
            {casus.team.map((lid) => (
              <nldd-list-item key={lid.id}>
                <nldd-icon-cell icon="person" size="16" />
                <nldd-text-cell
                  text={lid.person_naam}
                  width="full"
                  {...(lid.person_functie ? { 'supporting-text': lid.person_functie } : {})}
                />
                <nldd-cell>
                  <nldd-tag text={CASUSTEAM_ROL_LABELS[lid.rol] ?? lid.rol} color="neutral" size="sm" />
                </nldd-cell>
                <nldd-cell>
                  <NlddIconButton
                    icon="trash"
                    accessibleLabel="Uit het team halen"
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => removeTeamlid.mutate({ casusId: casus.id, rpId: lid.id })}
                  />
                </nldd-cell>
              </nldd-list-item>
            ))}
          </nldd-list>
        ) : (
          <nldd-text size="sm" color="secondary">Nog geen trekker of teamleden</nldd-text>
        )}
        <CasusTeamModal casus={showTeam ? casus : null} onClose={() => setShowTeam(false)} />
      </DetailSection>

      <DetailSection title="Startvoorwaarden" icon={<Icon name="check-mark-circle" size="sm" />} separated>
        <nldd-container gap="4">
          <Rij label="Intern of satelliet" value={sv.casustype ? CASUS_TYPE_LABELS[sv.casustype] : ''} />
          {/* De vragen zoals ze bij de start luidden, ook als het initiatief
              ze later anders stelt. */}
          {(sv.antwoorden ?? []).map((a) => (
            <Rij key={a.vraag_id} label={(a.vraag ?? a.vraag_id).replace(/\?\s*$/, '')} value={antwoordTekst(a.waarde)} />
          ))}
        </nldd-container>
        {/* De acceptatiecriteria zoals het team ze bij de start naliep. */}
        {sv.acceptatiecriteria && sv.acceptatiecriteria.length > 0 && (
          <nldd-container gap="6">
            <nldd-text size="xs" weight="medium" color="secondary">Acceptatiecriteria</nldd-text>
            {sv.acceptatiecriteria.map((a) => (
              <div key={a.criterium} className="hug hug-top hug-gap-8">
                {a.akkoord ? (
                  <nldd-icon icon="check-mark-circle" size="16" color="success" aria-hidden="true" />
                ) : (
                  <nldd-icon icon="circle" size="16" aria-hidden="true" />
                )}
                <nldd-container gap="2">
                  <nldd-text size="sm">
                    {a.criterium}
                    <span className="visually-hidden">{a.akkoord ? ' (voldaan)' : ' (niet voldaan)'}</span>
                  </nldd-text>
                  {a.opmerking && <nldd-text size="xs" color="secondary">{a.opmerking}</nldd-text>}
                </nldd-container>
              </div>
            ))}
          </nldd-container>
        )}
        {/* De starteisen van de soorten zoals het team ze bij de start naliep. */}
        {sv.start_eisen && sv.start_eisen.length > 0 && <EisenMomentopname titel="Starteisen" eisen={sv.start_eisen} />}
        {sv.toelichting && (
          <nldd-container gap="4">
            <nldd-text size="xs" weight="medium" color="secondary">Toelichting</nldd-text>
            <RichTextDisplay content={sv.toelichting} />
          </nldd-container>
        )}
        <nldd-text size="xs" color="secondary">Een eerste, kleine set. Schakels en kwartaalfocus volgen.</nldd-text>
      </DetailSection>

      {/* De eindeisen zoals het team ze naliep toen de casus in de laatste
          fase kwam. */}
      {eindEisen.length > 0 && (
        <DetailSection
          title="Eindeisen"
          icon={<Icon name="check-mark-circle" size="sm" />}
          count={eindEisen.filter((e) => e.akkoord).length}
          separated
        >
          <EisenMomentopname titel={`${eindEisen.filter((e) => e.akkoord).length} van ${eindEisen.length} af`} eisen={eindEisen} />
        </DetailSection>
      )}

      <DetailSection title="Herkomst" icon={<Icon name="inbox" size="sm" />} separated>
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-text size="sm">
            Gestart vanuit lead {casus.lead?.title ?? ''}
            {casus.organization ? ` (${casus.organization})` : ''}. De lead is alleen-lezen.
          </nldd-text>
          <NlddButton variant="neutral-transparent" size="sm" endIcon="arrow-right" onClick={() => openLeadDetail(casus.lead_id)} text="Open lead" />
        </nldd-container>
      </DetailSection>
    </nldd-container>
  );
}

function Rij({ label, value }: { label: string; value: string }) {
  return (
    <nldd-container layout="row" gap="8">
      <nldd-text size="sm" color="secondary">{label}:</nldd-text>
      <nldd-text size="sm" weight="medium">{value || 'Niet ingevuld'}</nldd-text>
    </nldd-container>
  );
}
