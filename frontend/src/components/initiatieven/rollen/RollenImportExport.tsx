import { useState } from 'react';

import { FileUpload } from '@/components/common/FileUpload';
import { NlddButton } from '@/components/nldd/NlddButton';
import { exportRollen } from '@/api/initiatiefRollen';
import { useImportRollen } from '@/hooks/useInitiatiefRollen';
import type { InitiatiefDetail, RollenImportResultaat } from '@/types';

/**
 * Rollen als JSON-bestand: exporteren, en importeren om snel rollen of
 * testdata in te laden. Importeren voegt toe of werkt bij op naam; er
 * verdwijnt niets.
 */
export function RollenImportExport({ initiatief, canEdit }: { initiatief: InitiatiefDetail; canEdit: boolean }) {
  const importeer = useImportRollen();
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [resultaat, setResultaat] = useState<RollenImportResultaat | null>(null);

  const exporteer = async () => {
    setBezig(true);
    setFout(null);
    try {
      const data = await exportRollen(initiatief.id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `rollen-${initiatief.slug || initiatief.naam.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setFout(e instanceof Error ? e.message : 'Exporteren mislukt');
    } finally {
      setBezig(false);
    }
  };

  const leesIn = async (file: File) => {
    setFout(null);
    setResultaat(null);
    let data: unknown;
    try {
      data = JSON.parse(await file.text());
    } catch {
      setFout(`${file.name} is geen geldig JSON-bestand.`);
      return;
    }
    try {
      setResultaat(await importeer.mutateAsync({ initiatiefId: initiatief.id, data }));
    } catch {
      // de melding is al getoond
    }
  };

  return (
    <nldd-container gap="12">
      <nldd-text size="xs" color="secondary">
        Een JSON-bestand met de cirkel, de rollen en hun raakvlakken. Importeren voegt rollen toe of werkt ze bij op
        naam; er verdwijnt niets. Een vervuller komt mee als het e-mailadres bij iemand in dit initiatief hoort.
      </nldd-text>
      <div>
        <NlddButton variant="secondary" size="sm" startIcon="arrow-down-in-bucket" onClick={() => void exporteer()} loading={bezig} text="Exporteren" />
      </div>
      {canEdit && (
        <FileUpload accept=".json,application/json" onFileSelect={(f) => void leesIn(f)} disabled={importeer.isPending} label="Sleep een JSON-bestand hierheen of klik om te importeren" />
      )}
      {fout && <nldd-text size="sm" color="critical">{fout}</nldd-text>}
      {resultaat && (
        <nldd-container gap="4">
          <nldd-text size="sm">
            {`Geïmporteerd: ${resultaat.aangemaakt} nieuw, ${resultaat.bijgewerkt} bijgewerkt, ${resultaat.raakvlakken} raakvlakken.`}
          </nldd-text>
          {resultaat.meldingen.map((m) => (
            <nldd-text key={m} size="xs" color="secondary">
              {m}
            </nldd-text>
          ))}
        </nldd-container>
      )}
    </nldd-container>
  );
}
