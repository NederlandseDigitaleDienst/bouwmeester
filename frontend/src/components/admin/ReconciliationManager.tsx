import { useCallback, useMemo, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listReconciliations,
  mergeReconciliation,
  ignoreReconciliation,
  scanOrphanHandmatig,
  manualMerge,
  type OrphanScanResult,
} from '@/api/reconciliation';
import { getOrganisatieFlatMetHistorisch } from '@/api/organisatie';
import { Card } from '@/components/common/Card';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';

type Status = 'open' | 'merged' | 'ignored';

const STATUS_LABEL: Record<Status, string> = {
  open: 'Open',
  merged: 'Gemerged',
  ignored: 'Genegeerd',
};

function ManualMergePanel() {
  const queryClient = useQueryClient();
  // include_historisch: een duplicaat kan soft-deleted zijn (geldig_tot
  // gevuld); zonder dit kun je zo'n rij niet als bron kiezen.
  const { data: eenheden = [] } = useQuery({
    queryKey: ['organisatie', 'flat', 'historisch'],
    queryFn: getOrganisatieFlatMetHistorisch,
  });

  // source verdwijnt, target blijft. Default-voorstel zodra beide gekozen
  // zijn: de gesyncte rij wordt target (officiële naam + tooi_uri blijven),
  // de handmatige rij wordt source. De admin kan met de swap-knop omkeren.
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [confirming, setConfirming] = useState(false);

  const byId = useMemo(
    () => new Map(eenheden.map((e) => [e.id, e])),
    [eenheden],
  );
  const source = sourceId ? byId.get(sourceId) : undefined;
  const target = targetId ? byId.get(targetId) : undefined;

  const options = useMemo(
    () =>
      eenheden
        .map((e) => ({
          value: e.id,
          label: e.naam,
          description: [
            e.type,
            e.afkorting,
            e.bron && e.bron !== 'handmatig' ? e.bron : null,
            e.geldig_tot ? 'historisch' : null,
          ]
            .filter(Boolean)
            .join(' · '),
        }))
        .sort((a, b) => a.label.localeCompare(b.label, 'nl')),
    [eenheden],
  );

  const mergeMutation = useMutation({
    mutationFn: () => manualMerge(sourceId, targetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
      queryClient.invalidateQueries({ queryKey: ['organisatie'] });
      setSourceId('');
      setTargetId('');
      setConfirming(false);
    },
  });

  // Slim default: zodra source een handmatige rij is en target een
  // gesyncte, klopt de richting al. Is het andersom gekozen, bied de
  // swap prominent aan via een hint (geen auto-swap — admin houdt regie).
  const sourceIsSynced = source?.bron && source.bron !== 'handmatig';
  const targetIsManual = !target?.bron || target.bron === 'handmatig';
  const suggestSwap = Boolean(
    source && target && sourceIsSynced && targetIsManual,
  );

  const swap = () => {
    setSourceId(targetId);
    setTargetId(sourceId);
  };

  const sameRow = sourceId !== '' && sourceId === targetId;
  // Een synthetische rij ('ZBO's en agentschappen', 'Marktpartijen en
  // overige', ...) is een container, geen echte eenheid. FK's daarheen
  // verhuizen is vrijwel altijd fout — blokkeer het als doel.
  const targetIsSynthetic = target?.bron === 'synthetisch';
  const canMerge = source && target && !sameRow && !targetIsSynthetic;

  return (
    <Card>
      <nldd-container gap="12">
        <nldd-container gap="4">
          <nldd-title size={4}><h3>Handmatig mergen</h3></nldd-title>
          <nldd-text size="sm" color="secondary">
            Twee eenheden samenvoegen die de scan niet vangt (bv. een
            seed-DG naast een organogram-rij met net andere naam). Alle
            plaatsingen, leads, opdrachten en sub-eenheden van de{' '}
            <strong>bron</strong> verhuizen naar het <strong>doel</strong>;
            de bron wordt verwijderd. Hou als doel de gesyncte rij aan
            (officiële naam en TOOI-koppeling blijven dan staan).
          </nldd-text>
        </nldd-container>

        <nldd-container layout="row" gap="12" vertical-alignment="center">
          <nldd-container width="fit-content" min-width="240px">
            <CreatableSelect
              label="Bron (verdwijnt)"
              value={sourceId}
              onChange={(v) => {
                setSourceId(v);
                setConfirming(false);
              }}
              options={options}
              placeholder="Zoek eenheid…"
              emptyMessage="Geen eenheid gevonden"
            />
          </nldd-container>
          <NlddIconButton
            icon="arrow-left-right"
            accessibleLabel="Bron en doel omwisselen"
            variant="neutral-transparent"
            disabled={!sourceId && !targetId}
            onClick={swap}
          />
          <nldd-container width="fit-content" min-width="240px">
            <CreatableSelect
              label="Doel (blijft)"
              value={targetId}
              onChange={(v) => {
                setTargetId(v);
                setConfirming(false);
              }}
              options={options}
              placeholder="Zoek eenheid…"
              emptyMessage="Geen eenheid gevonden"
            />
          </nldd-container>
        </nldd-container>

        {sameRow && (
          <nldd-text size="sm" color="critical">Bron en doel zijn dezelfde eenheid.</nldd-text>
        )}

        {targetIsSynthetic && (
          <nldd-text size="sm" color="critical">
            Het doel is een synthetische groep, geen echte eenheid. Kies
            een echte organisatie-eenheid als doel.
          </nldd-text>
        )}

        {suggestSwap && (
          <nldd-banner
            variant="warning"
            text={`De bron is een gesyncte rij (${source?.bron}) en het doel handmatig`}
            supporting-text="Meestal wil je het andersom zodat de gesyncte rij blijft bestaan."
          >
            <div slot="actions">
              <NlddButton variant="neutral-tinted" size="sm" text="Omwisselen" onClick={swap} />
            </div>
          </nldd-banner>
        )}

        {canMerge && !confirming && (
          <nldd-container horizontal-alignment="right">
            <NlddButton variant="primary" onClick={() => setConfirming(true)} text="Mergen…" />
          </nldd-container>
        )}

        {canMerge && confirming && (
          <nldd-banner
            variant="critical"
            text={`${source?.naam} wordt verwijderd`}
            supporting-text={`Alle referenties verhuizen naar ${target?.naam}${
              target?.bron && target.bron !== 'handmatig' ? ` (${target.bron})` : ''
            }. Dit is niet terug te draaien.`}
          >
            <div slot="actions">
              <NlddButton
                variant="secondary"
                text="Annuleren"
                onClick={() => setConfirming(false)}
                disabled={mergeMutation.isPending}
              />
              <NlddButton
                variant="destructive"
                text={mergeMutation.isPending ? 'Bezig…' : 'Definitief mergen'}
                onClick={() => mergeMutation.mutate()}
                disabled={mergeMutation.isPending}
              />
            </div>
          </nldd-banner>
        )}

        {mergeMutation.isError && (
          <nldd-text size="sm" color="critical">
            Merge mislukt:{' '}
            {mergeMutation.error instanceof Error
              ? mergeMutation.error.message
              : 'onbekende fout'}
          </nldd-text>
        )}
        {mergeMutation.isSuccess && (
          <nldd-text size="sm" color="success">Merge voltooid.</nldd-text>
        )}
      </nldd-container>
    </Card>
  );
}

export function ReconciliationManager() {
  const [status, setStatus] = useState<Status>('open');
  const statusFilterRef = useRef<HTMLElement>(null);
  const queryClient = useQueryClient();

  useNlddEvent(statusFilterRef, 'change', useCallback((e: Event) => setStatus(eventValue(e) as Status), []));

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['reconciliation', status],
    queryFn: () => listReconciliations(status),
  });

  const mergeMutation = useMutation({
    mutationFn: (id: string) => mergeReconciliation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
      queryClient.invalidateQueries({ queryKey: ['organisatie'] });
    },
  });

  const ignoreMutation = useMutation({
    mutationFn: (id: string) => ignoreReconciliation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
    },
  });

  const [scanResult, setScanResult] = useState<OrphanScanResult | null>(null);
  const orphanScanMutation = useMutation({
    mutationFn: scanOrphanHandmatig,
    onSuccess: (data) => {
      setScanResult(data);
      queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
    },
  });

  return (
    <nldd-container gap="16">
      <nldd-container gap="4">
        <nldd-title size={3}><h2>Reconciliatie van handmatige rijen met TOOI-data</h2></nldd-title>
        <nldd-text size="sm" color="secondary">
          TOOI-sync detecteert organisaties die ook handmatig zijn
          aangemaakt. Mergen voegt de handmatige rij samen met de TOOI-rij
          (alle leads, opdrachten en plaatsingen verhuizen). Negeren laat
          beide rijen bestaan.
        </nldd-text>
      </nldd-container>

      <Card>
        <nldd-container layout="row" gap="12" horizontal-alignment="left" vertical-alignment="center">
          <nldd-text size="sm">
            <strong>Scan op afkorting/naam-match:</strong> zoekt handmatige
            rijen (vaak FCC-import) die alsnog matchen op een TOOI-rij.
            Genereert open reconciliations.
            {scanResult && (
              <nldd-text size="sm" color="secondary">
                {' '}Laatste run: {scanResult.scanned} gescand,
                {' '}{scanResult.found_match} matches,
                {' '}{scanResult.new_reconciliations} nieuw,
                {' '}{scanResult.already_pending} al open.
              </nldd-text>
            )}
          </nldd-text>
          <NlddButton
            onClick={() => orphanScanMutation.mutate()}
            disabled={orphanScanMutation.isPending}
            variant="secondary"
            text={orphanScanMutation.isPending ? 'Bezig…' : 'Scan starten'}
          />
        </nldd-container>
      </Card>

      <ManualMergePanel />

      <nldd-toggle-button-group ref={statusFilterRef} type="radio" accessible-label="Filter op status">
        {(['open', 'merged', 'ignored'] as const).map((s) => (
          <nldd-toggle-button
            key={s}
            text={`${STATUS_LABEL[s]}${status === s ? ` (${items.length})` : ''}`}
            value={s}
            selected={status === s ? true : undefined}
          />
        ))}
      </nldd-toggle-button-group>

      {isLoading && <LoadingSpinner />}

      {!isLoading && items.length === 0 && (
        <Card>
          <EmptyState
            icon="inbox"
            title={
              status === 'open'
                ? 'Geen open reconciliaties'
                : status === 'merged'
                  ? 'Geen gemergede reconciliaties'
                  : 'Geen genegeerde reconciliaties'
            }
          />
        </Card>
      )}

      {items.map((item) => (
        <Card key={item.id}>
          <nldd-container gap="16">
            <nldd-container layout="row" gap="12" vertical-alignment="center">
              <nldd-tag text={item.match_reden} size="sm" />
              <nldd-text size="xs" color="secondary">
                {new Date(item.created_at).toLocaleDateString('nl-NL', {
                  day: '2-digit',
                  month: 'short',
                  year: 'numeric',
                })}
              </nldd-text>
            </nldd-container>

            <nldd-container layout="row" gap="16" vertical-alignment="center">
              {/* Handmatige rij */}
              <nldd-container width="fit-content" min-width="200px" padding="12" gap="4">
                <nldd-text size="xs" color="warning" weight="medium">Handmatig</nldd-text>
                <nldd-text size="sm" weight="medium">{item.handmatige_naam}</nldd-text>
                {item.handmatige_afkorting && (
                  <nldd-text size="xs" color="secondary">{item.handmatige_afkorting}</nldd-text>
                )}
              </nldd-container>

              <nldd-icon icon="arrow-right" size="20" color="secondary-content" />

              {/* Kandidaat */}
              <nldd-container width="fit-content" min-width="200px" padding="12" gap="4">
                <nldd-text size="xs" color="accent" weight="medium">
                  {item.kandidaat_bron.toUpperCase()}
                </nldd-text>
                <nldd-text size="sm" weight="medium">{item.kandidaat_naam ?? '—'}</nldd-text>
                {item.kandidaat_tooi_uri && (
                  <nldd-text size="xs" color="secondary">{item.kandidaat_tooi_uri}</nldd-text>
                )}
              </nldd-container>
            </nldd-container>

            {status === 'open' && (
              <nldd-container horizontal-alignment="right" layout="row" gap="8">
                <NlddButton
                  variant="secondary"
                  text="Negeren"
                  startIcon="dismiss"
                  onClick={() => ignoreMutation.mutate(item.id)}
                  disabled={ignoreMutation.isPending && ignoreMutation.variables === item.id}
                />
                <span
                  title={
                    !item.kandidaat_id
                      ? 'Kandidaat-rij is verwijderd; kan niet mergen'
                      : 'Verplaats alle plaatsingen, leads en opdrachten naar de kandidaat-rij en verwijder de handmatige rij'
                  }
                >
                  <NlddButton
                    variant="primary"
                    text="Mergen"
                    startIcon="check-mark"
                    onClick={() => mergeMutation.mutate(item.id)}
                    disabled={
                      !item.kandidaat_id ||
                      (mergeMutation.isPending && mergeMutation.variables === item.id)
                    }
                  />
                </span>
              </nldd-container>
            )}
          </nldd-container>
        </Card>
      ))}
    </nldd-container>
  );
}
