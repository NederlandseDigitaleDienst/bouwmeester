import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { NlddButton } from '@/components/nldd/NlddButton';
import { LeadIntakeDialog } from '@/components/leads/LeadIntakeDialog';
import { useParseLeadIntake } from '@/hooks/useLeads';
import { usePermissions } from '@/hooks/usePermissions';
import type { LeadParseResult } from '@/types';
import { INITIATIEVEN_PATH } from '@/utils/initiatiefRoutes';

interface SharedData {
  title: string;
  text: string;
  files: File[];
  previews: string[];
}

async function readSharedData(): Promise<SharedData | null> {
  try {
    const cache = await caches.open('share-target-cache');

    const metaResp = await cache.match('/_share-meta');
    if (!metaResp) return null;
    const meta = await metaResp.json();

    const files: File[] = [];
    const previews: string[] = [];

    for (let i = 0; i < meta.fileCount; i++) {
      const fileResp = await cache.match(`/_share-file-${i}`);
      if (!fileResp) continue;
      const blob = await fileResp.blob();
      const filename = fileResp.headers.get('X-Filename') || `shared-${i}.jpg`;
      const contentType = fileResp.headers.get('Content-Type') || 'image/jpeg';
      files.push(new File([blob], filename, { type: contentType }));
      previews.push(URL.createObjectURL(blob));
    }

    // Clean up cache
    await cache.delete('/_share-meta');
    for (let i = 0; i < meta.fileCount; i++) {
      await cache.delete(`/_share-file-${i}`);
    }

    return {
      title: meta.title || '',
      text: meta.text || '',
      files,
      previews,
    };
  } catch {
    return null;
  }
}

export function ShareTargetPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const received = searchParams.get('received') === '1';

  const [sharedData, setSharedData] = useState<SharedData | null>(null);
  const [parseResult, setParseResult] = useState<LeadParseResult | null>(null);
  const [showDialog, setShowDialog] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parseMutation = useParseLeadIntake();
  const { hasPermission } = usePermissions();
  const canCreateLeads = hasPermission('lead:read');

  // Read shared data from cache on mount
  useEffect(() => {
    if (!received || !canCreateLeads) return;
    readSharedData().then((data) => {
      if (data && data.files.length > 0) {
        setSharedData(data);
      } else {
        setError('Geen afbeeldingen ontvangen.');
      }
    });
  }, [received]);

  // Auto-parse when shared data arrives
  useEffect(() => {
    if (!sharedData || parsing || parseResult) return;

    setParsing(true);
    const rawText = [sharedData.title, sharedData.text].filter(Boolean).join('\n') || undefined;

    parseMutation.mutateAsync({ rawText, files: sharedData.files })
      .then((result) => {
        setParseResult(result);
        setShowDialog(true);
        setParsing(false);
      })
      .catch(() => {
        setError('Kon de afbeelding niet analyseren. Probeer het opnieuw.');
        setParsing(false);
      });
  }, [sharedData]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDialogClose = () => {
    setShowDialog(false);
    // Clean up blob URLs
    sharedData?.previews.forEach(URL.revokeObjectURL);
    navigate(INITIATIEVEN_PATH);
  };

  // No lead permission — show access denied
  if (received && !canCreateLeads) {
    return (
      <nldd-simple-section width="400px" horizontal-alignment="center" padding-block="80">
        <nldd-inline-dialog
          icon="lock-closed"
          icon-color="warning"
          text="Geen toegang"
          supporting-text="Je hebt geen rechten om leads aan te maken. Neem contact op met een beheerder."
        >
          <NlddButton
            slot="actions"
            text="Naar startpagina"
            variant="secondary"
            onClick={() => navigate('/')}
          />
        </nldd-inline-dialog>
      </nldd-simple-section>
    );
  }

  // Not a share — show instructions
  if (!received) {
    return (
      <nldd-simple-section width="400px" horizontal-alignment="center" padding-block="80">
        <nldd-inline-dialog
          icon="share"
          icon-color="accent"
          text="Deel naar Bouwmeester"
          supporting-text="Deel een afbeelding vanuit je telefoon (foto's, WhatsApp, e-mail) via het deelmenu en kies Bouwmeester. De afbeelding wordt automatisch geanalyseerd en omgezet naar een nieuwe lead."
        >
          <nldd-text size="xs" color="secondary" horizontal-alignment="center">
            <p>Vereist dat de app is geinstalleerd via &quot;Toevoegen aan startscherm&quot;.</p>
          </nldd-text>
          <NlddButton
            slot="actions"
            text="Naar leads"
            variant="secondary"
            onClick={() => navigate(INITIATIEVEN_PATH)}
          />
        </nldd-inline-dialog>
      </nldd-simple-section>
    );
  }

  // Error state
  if (error) {
    return (
      <nldd-simple-section width="400px" horizontal-alignment="center" padding-block="80">
        <nldd-inline-dialog variant="alert" text="Oeps" supporting-text={error}>
          <NlddButton
            slot="actions"
            text="Naar leads"
            variant="secondary"
            onClick={() => navigate(INITIATIEVEN_PATH)}
          />
        </nldd-inline-dialog>
      </nldd-simple-section>
    );
  }

  // Parsing state — show preview + spinner
  return (
    <>
      <nldd-simple-section width="400px" horizontal-alignment="center" padding-block="48">
        <nldd-container gap="32" horizontal-alignment="center">
          {/* Image previews */}
          {sharedData && sharedData.previews.length > 0 && (
            <nldd-container layout="row" gap="12" horizontal-alignment="center">
              {sharedData.previews.map((src, i) => (
                // The border/shadow frame around the crop is a one-off card
                // look nldd-image doesn't offer on its own, so that part stays
                // plain CSS; the crop itself is nldd-image's job.
                <div
                  key={i}
                  style={{
                    borderRadius: '16px',
                    overflow: 'hidden',
                    border: '1px solid var(--primitives-color-neutral-200)',
                    boxShadow: 'var(--primitives-box-shadows-level-1)',
                  }}
                >
                  <nldd-image
                    src={src}
                    alt={`Gedeelde afbeelding ${i + 1}`}
                    width="128"
                    height={128}
                    object-fit="cover"
                  />
                </div>
              ))}
            </nldd-container>
          )}

          {/* Status */}
          {parsing && (
            <nldd-inline-dialog
              variant="loading"
              text="Afbeelding analyseren..."
              supporting-text="Contactgegevens en organisatie worden herkend"
            />
          )}

          {!parsing && !sharedData && !error && (
            <nldd-inline-dialog variant="loading" text="Gedeelde data ophalen..." />
          )}
        </nldd-container>
      </nldd-simple-section>

      {/* Lead creation dialog with parsed data */}
      <LeadIntakeDialog
        open={showDialog}
        onClose={handleDialogClose}
        sharedParseResult={parseResult ?? undefined}
        sharedFiles={sharedData?.files}
      />
    </>
  );
}
