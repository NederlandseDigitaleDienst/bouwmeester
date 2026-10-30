import { useCallback, useEffect, useRef, useState } from 'react';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Icon } from '@/components/nldd/Icon';
import { eventValue, orUndef, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import {
  useUpdateInitiatief,
  useUpdateInitiatiefSettings,
} from '@/hooks/useInitiatieven';
import type { InitiatiefDetail, InitiatiefSettingsUpdate, InitiatiefUpdate } from '@/types';
import { ColumnsManager } from '@/components/leads/ColumnsManager';
import { InitiatiefKleurPicker } from './InitiatiefKleurPicker';
import { InstellingenBlok } from './InstellingenBlok';
import { CasusSoortenBeheer } from './CasusSoortenBeheer';
import { CasusFunnelEditor } from './CasusFunnelEditor';
import { useCasusSoorten } from '@/hooks/useCasusSoorten';
import { NlddButton } from '@/components/nldd/NlddButton';
import { EisenLijst } from './EisenLijst';
import { StartvragenEditor } from './StartvragenEditor';

/**
 * The "Instellingen" tab: things set once. Name, description and color are
 * edited in place here, which replaces the separate edit dialog the old
 * modal needed because it had no room left. Contributors may change those;
 * everything below them is the eigenaar's.
 *
 * Elk onderdeel is een inklapbaar blok met de stand van zaken in de kop:
 * dicht is de tab een overzicht, en je klapt open wat je wilt aanpassen.
 */
export function InitiatiefInstellingen({ initiatief }: { initiatief: InitiatiefDetail }) {
  const isEigenaar = initiatief.access_level === 'eigenaar';
  const canEdit = isEigenaar || initiatief.access_level === 'contributor';

  const { data: soorten } = useCasusSoorten(isEigenaar ? initiatief.id : null);
  const aantalSoorten = soorten?.length ?? 0;
  const aantalCriteria = initiatief.acceptatiecriteria?.length ?? 0;
  const aantalVragen = initiatief.startvragen?.length ?? 0;
  const criteriaSamenvatting = `${aantalVragen} ${aantalVragen === 1 ? 'vraag' : 'vragen'} · ${
    aantalCriteria ? `${aantalCriteria} ${aantalCriteria === 1 ? 'criterium' : 'criteria'}` : 'nog geen criteria'
  } voor satellietcasussen`;

  return (
    <nldd-container gap="12">
      {canEdit && (
        <InstellingenBlok icon="pencil" titel="Algemeen" samenvatting={initiatief.naam}>
          <GeneralSettings initiatief={initiatief} />
        </InstellingenBlok>
      )}
      {isEigenaar && (
        <>
          <InstellingenBlok
            icon="globe"
            titel="Publieke pagina en funnel"
            samenvatting={`Publieke pagina ${initiatief.public_page_enabled ? 'aan' : 'uit'} · funnel-velden ${initiatief.funnel_enabled ? 'aan' : 'uit'}`}
          >
            <FeatureSettings initiatief={initiatief} />
          </InstellingenBlok>
          <InstellingenBlok icon="check-mark-circle" titel="Casus starten" samenvatting={criteriaSamenvatting}>
            <CasusStartenSettings initiatief={initiatief} />
          </InstellingenBlok>
          <InstellingenBlok
            icon="columns-3"
            titel="Casusfunnel"
            samenvatting={`${initiatief.casus_fases?.length ?? 0} fases${initiatief.casus_fases_is_voorstel === false ? '' : ' · voorstel'}`}
          >
            <CasusFunnelEditor initiatief={initiatief} />
          </InstellingenBlok>
          <InstellingenBlok
            icon="tag"
            titel="Casussoorten"
            samenvatting={aantalSoorten ? `${aantalSoorten} ${aantalSoorten === 1 ? 'soort' : 'soorten'}` : 'nog geen soorten'}
          >
            <CasusSoortenBeheer initiatiefId={initiatief.id} />
          </InstellingenBlok>
          <InstellingenBlok icon="columns-3" titel="Funnel-kolommen">
            <ColumnsManager initiatiefId={initiatief.id} />
          </InstellingenBlok>
        </>
      )}
    </nldd-container>
  );
}

/** Controlled `nldd-text-field` for the initiatief name. */
function NaamField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddValue(ref, value);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return <nldd-text-field ref={ref} required accessible-label="Naam" />;
}

function savedForm(initiatief: InitiatiefDetail): InitiatiefUpdate {
  return {
    naam: initiatief.naam,
    beschrijving: initiatief.beschrijving ?? '',
    kleur: initiatief.kleur,
  };
}

function GeneralSettings({ initiatief }: { initiatief: InitiatiefDetail }) {
  const updateMutation = useUpdateInitiatief();
  const saved = savedForm(initiatief);
  const [form, setForm] = useState<InitiatiefUpdate>(saved);

  // Follow the server when the saved values change (after our own save, or a
  // refetch), so "Opslaan" goes back to disabled.
  const savedKey = `${saved.naam}|${saved.beschrijving}|${saved.kleur ?? ''}`;
  useEffect(() => {
    setForm(savedForm(initiatief));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedKey]);

  const dirty =
    form.naam !== saved.naam ||
    (form.beschrijving ?? '') !== (saved.beschrijving ?? '') ||
    form.kleur !== saved.kleur;

  const canEdit =
    initiatief.access_level === 'eigenaar' || initiatief.access_level === 'contributor';
  if (!canEdit) return null;

  return (
    <nldd-container gap="16">
      <nldd-form-field label="Naam">
        <NaamField value={form.naam || ''} onChange={(v) => setForm((f) => ({ ...f, naam: v }))} />
      </nldd-form-field>
      <RichTextFormField
        label="Beschrijving"
        value={form.beschrijving || ''}
        onChange={(value) => setForm((f) => ({ ...f, beschrijving: value }))}
        rows={3}
      />
      <nldd-form-field label="Kleur">
        <InitiatiefKleurPicker value={form.kleur} onChange={(kleur) => setForm((f) => ({ ...f, kleur }))} />
      </nldd-form-field>
      <nldd-container layout="row" gap="8" horizontal-alignment="right">
        <NlddButton variant="secondary" size="sm" disabled={!dirty} onClick={() => setForm(saved)} text="Herstellen" />
        <NlddButton
          size="sm"
          loading={updateMutation.isPending}
          disabled={!dirty || !form.naam?.trim()}
          onClick={() => updateMutation.mutateAsync({ id: initiatief.id, data: form })}
          text="Opslaan"
        />
      </nldd-container>
    </nldd-container>
  );
}

/**
 * Wat je doorloopt als je een casus start, op één plek: de startvragen (per
 * initiatief te beheren, StartvragenEditor; de vraag naar intern of
 * satelliet ligt vast) en de acceptatiecriteria voor satellietcasussen, die het initiatief
 * zelf beheert. Bij een satellietcasus vink je die per casus af, met een
 * uitleg per criterium. Anders dan de DoD is er geen standaardlijst.
 */
function CasusStartenSettings({ initiatief }: { initiatief: InitiatiefDetail }) {
  const settingsMutation = useUpdateInitiatiefSettings();
  const geldend = initiatief.acceptatiecriteria ?? [];
  const [items, setItems] = useState<string[]>(geldend);
  // Na opslaan of een herlaadactie de lijst van de server volgen.
  const geldendKey = JSON.stringify(geldend);
  useEffect(() => {
    setItems(JSON.parse(geldendKey) as string[]);
  }, [geldendKey]);

  const schoon = items.map((x) => x.trim()).filter(Boolean);
  const dirty = JSON.stringify(schoon) !== geldendKey;

  return (
    <nldd-container gap="20">
      <nldd-container gap="8">
        <nldd-text size="sm" weight="bold">Startvragen</nldd-text>
        <nldd-text size="sm" color="secondary">
          Bij Nieuwe casus en Casus starten beantwoord je deze vragen. Per vraag kies je het soort antwoord, of
          hij verplicht is en of het antwoord op het casuskaartje komt. Een casus houdt de vragen zoals ze bij
          zijn start luidden.
        </nldd-text>
        <StartvragenEditor initiatief={initiatief} />
      </nldd-container>
      <nldd-container gap="12">
        <nldd-text size="sm" weight="bold">Acceptatiecriteria voor satellietcasussen</nldd-text>
        <nldd-text size="sm" color="secondary">
          Alleen bij een satellietcasus loop je deze lijst na: per criterium een vinkje en een uitleg of
          opmerking. Bij een interne casus niet.
        </nldd-text>
        <EisenLijst
          items={items}
          onChange={setItems}
          naam="Criterium"
          placeholder="Nieuw criterium, bijvoorbeeld: er is een partner die meedoet"
          leeg="Nog geen criteria. Voeg er hieronder een toe."
          nieuwLabel="Nieuw criterium"
        />
        <nldd-container layout="row" gap="8" horizontal-alignment="right">
          <NlddButton variant="secondary" size="sm" disabled={!dirty} onClick={() => setItems(geldend)} text="Herstellen" />
          <NlddButton
            size="sm"
            onClick={() => settingsMutation.mutate({ id: initiatief.id, data: { acceptatiecriteria: schoon } })}
            loading={settingsMutation.isPending}
            disabled={!dirty}
            text="Opslaan"
          />
        </nldd-container>
      </nldd-container>
    </nldd-container>
  );
}

/** Public page and funnel weighting: the two opt-in features, eigenaar only. */
function FeatureSettings({ initiatief }: { initiatief: InitiatiefDetail }) {
  const settingsMutation = useUpdateInitiatiefSettings();
  const [pendingPublic, setPendingPublic] = useState(false);
  const [scoreLabels, setScoreLabels] = useState({
    score_strategisch_label: initiatief.score_strategisch_label ?? '',
    score_politiek_label: initiatief.score_politiek_label ?? '',
    score_positie_label: initiatief.score_positie_label ?? '',
  });
  const [slugDraft, setSlugDraft] = useState(initiatief.slug ?? '');
  const [slugError, setSlugError] = useState<string | null>(null);

  const save = (data: InitiatiefSettingsUpdate) =>
    settingsMutation.mutateAsync({ id: initiatief.id, data });

  const handlePublicToggle = () => {
    if (initiatief.public_page_enabled) {
      // Turning off — no confirmation needed.
      save({ public_page_enabled: false });
    } else {
      setPendingPublic(true);
    }
  };

  const confirmPublicEnable = async () => {
    await save({ public_page_enabled: true });
    setPendingPublic(false);
  };

  const persistLabels = (labels: typeof scoreLabels) => {
    save({
      score_strategisch_label: labels.score_strategisch_label || null,
      score_politiek_label: labels.score_politiek_label || null,
      score_positie_label: labels.score_positie_label || null,
    });
  };

  const publicUrl = initiatief.slug ? `/c/${initiatief.slug}` : null;

  return (
    <nldd-container gap="8">
      <nldd-container gap="16">
        {/* Publieke pagina */}
        <nldd-card>
          <nldd-container gap="12" padding="16">
            <nldd-container layout="row" gap="6" vertical-alignment="center">
              <Icon name="globe" size="sm" />
              <nldd-text size="xs" weight="bold" color="secondary">
                Publieke pagina
              </nldd-text>
            </nldd-container>

            <ToggleRow
              icon="globe"
              label="Publieke pagina inschakelen"
              description={
                publicUrl
                  ? `Pagina bereikbaar via ${publicUrl} voor iedereen met de link.`
                  : 'Stel eerst een slug in om de pagina aan te kunnen zetten.'
              }
              enabled={initiatief.public_page_enabled}
              onToggle={handlePublicToggle}
              loading={settingsMutation.isPending}
              disabled={!publicUrl}
            />

            <nldd-container gap="6" style={initiatief.public_page_enabled || !initiatief.slug ? undefined : { opacity: 0.6 }}>
              <nldd-form-field label="Slug" supporting-label="publieke URL-segment">
                {initiatief.slug ? (
                  initiatief.public_page_enabled ? (
                    <nldd-link
                      href={`/c/${initiatief.slug}`}
                      target="_blank"
                      size="sm"
                      text={`/c/${initiatief.slug}`}
                      end-icon="external-link"
                    />
                  ) : (
                    <nldd-text size="sm">/c/{initiatief.slug}</nldd-text>
                  )
                ) : (
                  <nldd-container gap="6">
                    <nldd-text size="xs" color="secondary">
                      Nog geen slug ingesteld. Kies kleine letters, cijfers en
                      streepjes (bv. <code>regelrecht</code>).
                    </nldd-text>
                    <nldd-container layout="row" gap="8" vertical-alignment="top">
                      <nldd-text size="sm" color="secondary">/c/</nldd-text>
                      <nldd-container width="fit-content" className="row-fill">
                        <SlugDraftField
                          value={slugDraft}
                          onChange={(v) => {
                            setSlugDraft(v.toLowerCase());
                            setSlugError(null);
                          }}
                        />
                      </nldd-container>
                      <NlddButton
                        size="sm"
                        onClick={async () => {
                          const trimmed = slugDraft.trim();
                          if (!trimmed) return;
                          try {
                            await save({ slug: trimmed });
                          } catch (err) {
                            const msg =
                              err instanceof Error ? err.message : 'Onbekende fout';
                            setSlugError(msg);
                          }
                        }}
                        disabled={!slugDraft.trim() || settingsMutation.isPending}
                        text="Instellen"
                      />
                    </nldd-container>
                    {slugError && <nldd-text size="xs" color="critical">{slugError}</nldd-text>}
                  </nldd-container>
                )}
              </nldd-form-field>
            </nldd-container>
          </nldd-container>
        </nldd-card>

        {/* Funnel-afweging */}
        <nldd-card>
          <nldd-container gap="12" padding="16">
            <nldd-container layout="row" gap="6" vertical-alignment="center">
              <Icon name="person-badge-plus" size="sm" />
              <nldd-text size="xs" weight="bold" color="secondary">
                Funnel-afweging
              </nldd-text>
            </nldd-container>

            <ToggleRow
              icon="person-badge-plus"
              label="Funnel-velden op leads tonen"
              description="Engagement type + drie scores (strategisch/politiek/positie) op leads in dit initiatief."
              enabled={initiatief.funnel_enabled}
              onToggle={() =>
                save({ funnel_enabled: !initiatief.funnel_enabled })
              }
              loading={settingsMutation.isPending}
            />

            {initiatief.funnel_enabled && (
              <nldd-container gap="8" padding-top="8">
                <nldd-text size="xs" color="secondary">
                  Optionele eigen labels voor de drie funnel-scores. Leeg laten
                  gebruikt de standaard.
                </nldd-text>
                <nldd-container layout="grid" column-count={1} sm-column-count={3} gap="8">
                  {(
                    [
                      ['score_strategisch_label', 'Strategisch belang'],
                      ['score_politiek_label', 'Politiek belang'],
                      ['score_positie_label', 'Positie / omgeving'],
                    ] as const
                  ).map(([key, fallback]) => (
                    <nldd-form-field key={key} label={fallback}>
                      <ScoreLabelField
                        value={scoreLabels[key]}
                        placeholder={fallback}
                        onCommit={(v) => {
                          const next = { ...scoreLabels, [key]: v };
                          setScoreLabels(next);
                          persistLabels(next);
                        }}
                      />
                    </nldd-form-field>
                  ))}
                </nldd-container>
              </nldd-container>
            )}
          </nldd-container>
        </nldd-card>
      </nldd-container>

      <ConfirmDialog
        open={pendingPublic}
        onClose={() => setPendingPublic(false)}
        onConfirm={confirmPublicEnable}
        title="Publieke pagina inschakelen"
        confirmLabel="Inschakelen"
        loading={settingsMutation.isPending}
      >
        Iedereen met de link <code>/c/{initiatief.slug}</code> kan straks de
        naam, beschrijving en gepubliceerde updates van dit initiatief zien.
        Leads, scores en stakeholders blijven privé. Doorgaan?
      </ConfirmDialog>
    </nldd-container>
  );
}

/** Controlled `nldd-text-field` for the slug draft (before it is saved). */
function SlugDraftField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return (
    <nldd-text-field
      ref={ref}
      value={value}
      placeholder="regelrecht"
      accessible-label="Slug"
    />
  );
}

/** A score-label field: value commits on `change` (blur/Enter), matching the previous onBlur-persist behaviour. */
function ScoreLabelField({
  value,
  placeholder,
  onCommit,
}: {
  value: string;
  placeholder: string;
  onCommit: (v: string) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddValue(ref, value);
  useNlddEvent(ref, 'change', useCallback((e: Event) => onCommit(eventValue(e)), [onCommit]));
  return <nldd-text-field ref={ref} size="sm" placeholder={placeholder} accessible-label={placeholder} />;
}

/**
 * A labelled row with a switch. `nldd-switch-field` has no supporting-text
 * slot for a description line, so this composes the bare `nldd-switch`
 * control with the label/description markup the row already needs, rather
 * than fighting the field variant's fixed layout.
 */
function ToggleRow({
  icon,
  label,
  description,
  enabled,
  onToggle,
  loading,
  disabled,
}: {
  icon: string;
  label: string;
  description: string;
  enabled: boolean;
  onToggle: () => void;
  loading?: boolean;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', useCallback(() => onToggle(), [onToggle]));

  return (
    <nldd-container layout="row" gap="12" vertical-alignment="top">
      {/* The label block takes what the switch does not need. `fit-content`
          on its own makes a container collapse to its narrowest word, which
          set this label one letter per line. */}
      <nldd-container layout="row" width="fit-content" className="row-fill" gap="8" vertical-alignment="top">
        <Icon name={icon} size="sm" />
        <nldd-container gap="0">
          <nldd-text size="sm" weight="medium">{label}</nldd-text>
          <nldd-text size="xs" color="secondary">{description}</nldd-text>
        </nldd-container>
      </nldd-container>
      <nldd-switch
        ref={ref}
        checked={orUndef(enabled)}
        {...(loading || disabled ? { disabled: true } : {})}
        accessible-label={label}
      />
    </nldd-container>
  );
}

