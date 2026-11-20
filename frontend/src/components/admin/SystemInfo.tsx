import type { ReactNode } from 'react';
import { useVersionInfo } from '@/hooks/useAdmin';
import { MattermostChannelOverviewTable } from './MattermostChannelOverview';
import { WorkerHealthTable } from './WorkerHealthTable';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

const FRONTEND_GIT_SHA = (import.meta.env.VITE_GIT_SHA ?? '') as string;
const FRONTEND_BUILD_TIME = (import.meta.env.VITE_BUILD_TIME ?? '') as string;

function formatBuildTime(iso: string): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('nl-NL', {
    dateStyle: 'long',
    timeStyle: 'short',
    timeZone: 'Europe/Amsterdam',
  });
}

function CommitLink({ sha, repoUrl }: { sha: string; repoUrl: string }) {
  if (!sha) return <nldd-text color="secondary"><p>–</p></nldd-text>;
  if (!repoUrl) return <nldd-text><p>{sha}</p></nldd-text>;
  return (
    <nldd-link href={`${repoUrl}/commit/${sha}`} target="_blank" end-icon="square-arrow-right-top" text={sha} />
  );
}

/** One label/value row of the version info, label at a fixed width so values line up. */
function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <nldd-container layout="row" gap="16" vertical-alignment="center">
      <nldd-container width="160px">
        <nldd-text size="sm" color="secondary"><p>{label}</p></nldd-text>
      </nldd-container>
      <nldd-text size="sm"><p>{children}</p></nldd-text>
    </nldd-container>
  );
}

export function SystemInfo() {
  const { data, isLoading, error } = useVersionInfo();

  if (isLoading) return <LoadingSpinner padding="32" />;

  if (error) {
    return <nldd-text size="sm" color="critical"><p>Kon versie-informatie niet ophalen.</p></nldd-text>;
  }

  const backendSha = data?.git_sha || '';
  const backendBuildTime = data?.build_time || '';
  const repoUrl = data?.repo_url || '';
  const hasAny = backendSha || backendBuildTime || FRONTEND_GIT_SHA || FRONTEND_BUILD_TIME;
  const drift = backendSha && FRONTEND_GIT_SHA && backendSha !== FRONTEND_GIT_SHA;

  return (
    <nldd-container max-width="720px" gap="32">
      <nldd-container gap="4">
        <nldd-title size="display-3"><h2>Systeem</h2></nldd-title>
        <nldd-text size="sm" color="secondary">
          <p>
            Welke versie van Bouwmeester draait er nu, en zijn de
            achtergrondprocessen gezond.
          </p>
        </nldd-text>
      </nldd-container>

      {!hasAny ? (
        <nldd-inline-dialog
          text="Geen versie-informatie beschikbaar"
          supporting-text="In lokale dev-builds zijn de build-args niet gezet; ze worden alleen door de CI-build gevuld."
        />
      ) : (
        <nldd-container gap="16">
          {drift ? (
            <nldd-banner
              variant="warning"
              text="Backend en frontend draaien op verschillende commits"
              supporting-text="Dit kan tijdelijk voorkomen tijdens een deploy, maar mag niet blijvend zijn."
            />
          ) : null}

          <nldd-container gap="12">
            <InfoRow label="Backend-commit"><CommitLink sha={backendSha} repoUrl={repoUrl} /></InfoRow>
            <InfoRow label="Backend gebouwd">{formatBuildTime(backendBuildTime)}</InfoRow>
            <InfoRow label="Frontend-commit"><CommitLink sha={FRONTEND_GIT_SHA} repoUrl={repoUrl} /></InfoRow>
            <InfoRow label="Frontend gebouwd">{formatBuildTime(FRONTEND_BUILD_TIME)}</InfoRow>
          </nldd-container>
        </nldd-container>
      )}

      <WorkerHealthTable />

      <MattermostChannelOverviewTable />
    </nldd-container>
  );
}
