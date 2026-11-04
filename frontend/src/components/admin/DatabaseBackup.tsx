import { useCallback, useRef, useState, useEffect } from 'react';
import { useToast } from '@/contexts/ToastContext';
import { FileUpload } from '@/components/common/FileUpload';
import { NlddButton } from '@/components/nldd/NlddButton';
import { eventValue, orUndef, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import {
  exportDatabase,
  getDatabaseInfo,
  importDatabase,
  resetDatabase,
} from '@/api/import-export';
import { usePermissions } from '@/hooks/usePermissions';
import type { DatabaseBackupInfo, DatabaseResetResult, DatabaseRestoreResult } from '@/types';

/**
 * The heading of one section: an icon in the section's colour, a title and a
 * line saying what the action does.
 *
 * The colour lives here and nowhere else. Painting the whole card as well put
 * red inside red inside red on the reset section, where three layers all said
 * "danger" and none of them said it louder than the others.
 */
function SectionHeader({
  icon,
  color,
  title,
  description,
}: {
  icon: string;
  color: 'accent' | 'warning' | 'critical';
  title: string;
  description: string;
}) {
  return (
    <nldd-container layout="row" gap="12" vertical-alignment="top">
      <nldd-icon icon={icon} size="24" color={color} box className="shrink-0" />
      <nldd-container width="fit-content" className="row-fill" gap="2">
        <nldd-title size={5}>
          <h2>{title}</h2>
        </nldd-title>
        <nldd-text size="sm" color="secondary">
          {description}
        </nldd-text>
      </nldd-container>
    </nldd-container>
  );
}

export function DatabaseBackup() {
  const { showError, showSuccess } = useToast();
  const { isSuperAdmin } = usePermissions();
  const [info, setInfo] = useState<DatabaseBackupInfo | null>(null);
  const [loadingInfo, setLoadingInfo] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [restoreResult, setRestoreResult] = useState<DatabaseRestoreResult | null>(null);
  const [confirmImport, setConfirmImport] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetConfirmText, setResetConfirmText] = useState('');
  const [showResetInput, setShowResetInput] = useState(false);
  const [resetResult, setResetResult] = useState<DatabaseResetResult | null>(null);
  const resetFieldRef = useRef<HTMLElement>(null);

  useNlddEvent(resetFieldRef, 'input', useCallback((e: Event) => setResetConfirmText(eventValue(e)), []));
  useNlddValue(resetFieldRef, resetConfirmText);

  useEffect(() => {
    getDatabaseInfo()
      .then(setInfo)
      .catch(() => setInfo(null))
      .finally(() => setLoadingInfo(false));
  }, []);

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportDatabase();
      showSuccess('Export voltooid — het bestand wordt gedownload.');
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Export mislukt';
      showError(msg);
    } finally {
      setExporting(false);
    }
  };

  const handleFileSelect = (file: File) => {
    setSelectedFile(file);
    setRestoreResult(null);
    setConfirmImport(false);
  };

  const handleImport = async () => {
    if (!selectedFile) return;

    if (!confirmImport) {
      setConfirmImport(true);
      return;
    }

    setImporting(true);
    setRestoreResult(null);
    try {
      const result = await importDatabase(selectedFile);
      setRestoreResult(result);
      if (result.success) {
        showSuccess(result.message);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Import mislukt';
      showError(msg);
    } finally {
      setImporting(false);
      setConfirmImport(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    setResetResult(null);
    try {
      const result = await resetDatabase(resetConfirmText);
      setResetResult(result);
      if (result.success) {
        showSuccess(result.message);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Reset mislukt';
      showError(msg);
    } finally {
      setResetting(false);
      setResetConfirmText('');
      setShowResetInput(false);
    }
  };

  return (
    <nldd-container max-width="640px" gap="24">
      {/* Exporteren: de veilige, alledaagse actie, dus geen waarschuwing en
          geen kleur. Wat er in de backup zit staat als bijzin onder de knop,
          niet als een blok tekst dat eerst gelezen moet worden. */}
      <nldd-card>
        <nldd-container gap="12" padding="16">
          <SectionHeader
            icon="download"
            color="accent"
            title="Database exporteren"
            description="Download een volledige backup van corpus, organisatie, personen, taken, audit trail en kamerstukken."
          />

          <nldd-container layout="row" gap="12" vertical-alignment="center">
            <NlddButton
              text="Database exporteren"
              startIcon="database"
              onClick={handleExport}
              disabled={exporting}
              loading={exporting}
            />
            {loadingInfo ? (
              // Inline next to the export button, so a bare indicator rather
              // than the full-width LoadingSpinner block.
              <nldd-activity-indicator size="16" />
            ) : info ? (
              <nldd-text size="xs" color="secondary">
                versie <code>{info.alembic_revision}</code>
                {info.encrypted ? ' · age-versleuteld' : ''}
              </nldd-text>
            ) : (
              <nldd-text size="xs" color="warning">
                Kon database-informatie niet ophalen
              </nldd-text>
            )}
          </nldd-container>
        </nldd-container>
      </nldd-card>

      {/* Terugzetten en wissen kunnen rechten aanmaken en wegnemen, dus
          alleen een systeembeheerder ziet ze. */}
      {isSuperAdmin && (
        <>
        {/* Importeren. De waarschuwing stond hier boven het uploadveld, dus je
            las een alarm over iets wat je nog niet gekozen had. Nu verschijnt
            hij bij het bestand dat je daadwerkelijk gaat terugzetten, waar hij
            over iets concreets gaat. */}
        <nldd-card>
          <nldd-container gap="12" padding="16">
            <SectionHeader
              icon="upload"
              color="warning"
              title="Database importeren"
              description="Herstel de database vanuit een backup-bestand. De huidige data wordt vervangen."
            />

            <FileUpload
              accept=".tar.gz,.tar.gz.age,.age"
              onFileSelect={handleFileSelect}
              disabled={importing}
              label="Sleep een backup-bestand hierheen of klik om te uploaden"
            />

            {selectedFile && (
              <nldd-container gap="12">
                <nldd-banner
                  variant={confirmImport ? 'critical' : 'warning'}
                  text={
                    confirmImport
                      ? 'Dit vervangt alle huidige data. Dit kan niet ongedaan worden gemaakt.'
                      : 'Import vervangt alle huidige data in de database'
                  }
                  supporting-text="Maak eerst een export als backup. De import kan enkele minuten duren; tijdens het importeren is de applicatie tijdelijk niet beschikbaar voor andere gebruikers."
                />

                {/* Bij de bevestiging staat annuleren vóór de onomkeerbare
                    actie: daar gaat de gebruiker op autopilot naartoe, en dat
                    hoort de veilige uitweg te zijn. */}
                <nldd-container layout="row" gap="8">
                  {confirmImport && (
                    <NlddButton
                      text="Annuleren"
                      variant="primary"
                      onClick={() => setConfirmImport(false)}
                    />
                  )}
                  <NlddButton
                    text={
                      importing
                        ? 'Bezig met importeren...'
                        : confirmImport
                          ? 'Ja, vervang alle data'
                          : 'Database importeren'
                    }
                    startIcon="upload"
                    variant={confirmImport ? 'destructive' : 'primary'}
                    onClick={handleImport}
                    disabled={importing}
                    loading={importing}
                  />
                </nldd-container>
              </nldd-container>
            )}

            {restoreResult && (
              <nldd-banner
                variant={restoreResult.success ? 'success' : 'critical'}
                text={restoreResult.message}
                supporting-text={
                  `${restoreResult.tables_restored} tabellen hersteld` +
                  (restoreResult.migrations_applied > 0
                    ? ` · ${restoreResult.migrations_applied} migraties toegepast`
                    : '') +
                  ` · versie ${restoreResult.alembic_revision_to}`
                }
              />
            )}
          </nldd-container>
        </nldd-card>

        {/* Resetten. Dezelfde kaart als de andere twee, niet een rood vlak met
            een rode banner met een rode knop erin: drie lagen rood zeggen drie
            keer hetzelfde en geen van alle luider. Het icoon en de knop dragen
            de kleur, en de volledige gevolgen staan er pas als je de actie in
            gang hebt gezet. */}
        <nldd-card>
          <nldd-container gap="12" padding="16">
            <SectionHeader
              icon="delete"
              color="critical"
              title="Database resetten"
              description="Wis alle data en begin opnieuw. Dit kan niet ongedaan worden gemaakt."
            />

            {!showResetInput ? (
              <NlddButton
                text="Database resetten"
                startIcon="delete"
                variant="destructive"
                onClick={() => setShowResetInput(true)}
              />
            ) : (
              <nldd-container gap="12">
                <nldd-banner
                  variant="critical"
                  text="Dit wist alle data behalve de toegangslijst en sessies"
                  supporting-text="Corpus, organisatie, personen en taken worden verwijderd. Admin-accounts worden opnieuw aangemaakt. De applicatie is tijdelijk niet beschikbaar tijdens het resetten."
                />

                <nldd-form-field label="Type RESET om te bevestigen">
                  <nldd-text-field
                    ref={resetFieldRef}
                    placeholder="RESET"
                    disabled={orUndef(resetting)}
                    width="240px"
                  />
                </nldd-form-field>

                {/* Annuleren eerst en als primary: dat is de veilige uitweg. */}
                <nldd-container layout="row" gap="8">
                  <NlddButton
                    text="Annuleren"
                    variant="primary"
                    disabled={resetting}
                    onClick={() => {
                      setShowResetInput(false);
                      setResetConfirmText('');
                    }}
                  />
                  <NlddButton
                    text={resetting ? 'Bezig met resetten...' : 'Ja, wis alle data'}
                    startIcon="delete"
                    variant="destructive"
                    onClick={handleReset}
                    disabled={resetting || resetConfirmText !== 'RESET'}
                    loading={resetting}
                  />
                </nldd-container>
              </nldd-container>
            )}

            {resetResult && (
              <nldd-banner
                variant={resetResult.success ? 'success' : 'critical'}
                text={resetResult.message}
                supporting-text={
                  `${resetResult.tables_cleared} tabellen gewist` +
                  (resetResult.admin_persons_created > 0
                    ? ` · ${resetResult.admin_persons_created} admin-accounts aangemaakt`
                    : '')
                }
              />
            )}
          </nldd-container>
        </nldd-card>
        </>
      )}
    </nldd-container>
  );
}
