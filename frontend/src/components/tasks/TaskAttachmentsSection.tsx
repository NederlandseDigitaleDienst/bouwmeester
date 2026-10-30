import { useRef, useState, type ReactNode } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { getTaskAttachmentDownloadUrl } from '@/api/tasks';
import { useDeleteTaskAttachment, useTaskAttachments, useUploadTaskAttachment } from '@/hooks/useTasks';
import type { TaskAttachment } from '@/types';

/**
 * Bestanden bij een taak, onderaan het taakdetail. Geen eigen kop: de
 * bestanden staan boven de knop Uploaden, waar je ze ook toevoegt. Op dezelfde
 * regel als Uploaden staat links `acties` (het taakdetail zet daar Verwijderen
 * van de taak), zodat de onderkant één regel met acties is.
 *
 * Per bestand: downloaden en verwijderen, verwijderen met een bevestiging.
 */
export function TaskAttachmentsSection({ taskId, acties }: { taskId: string; acties?: ReactNode }) {
  const { data: attachments = [] } = useTaskAttachments(taskId);
  const upload = useUploadTaskAttachment();
  const remove = useDeleteTaskAttachment();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [weg, setWeg] = useState<TaskAttachment | null>(null);
  const bezig = useRef(false);

  const onFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    for (const file of Array.from(e.target.files)) upload.mutate({ taskId, file });
    e.target.value = '';
  };

  const verwijder = async () => {
    if (!weg || bezig.current) return;
    bezig.current = true;
    try {
      await remove.mutateAsync({ taskId, attachmentId: weg.id });
      setWeg(null);
    } catch {
      // toast is al getoond
    } finally {
      bezig.current = false;
    }
  };

  return (
    <div style={{ borderTop: '1px solid var(--primitives-color-neutral-200)', paddingTop: '12px' }}>
      <nldd-container gap="8">
        {attachments.length > 0 && (
          <nldd-list appearance="simple" dividers="never" accessible-label="Bestanden bij deze taak">
            {attachments.map((att) => (
              <nldd-list-item key={att.id}>
                <nldd-container layout="row" gap="8" vertical-alignment="center" width="full" padding="4">
                  <nldd-icon icon="paperclip" size="16" aria-hidden="true" />
                  <nldd-text size="sm" className="truncate row-fill">{att.bestandsnaam}</nldd-text>
                  <nldd-text size="xs" color="secondary">{Math.round((att.bestandsgrootte ?? 0) / 1024)} KB</nldd-text>
                  <NlddIconButton
                    icon="download"
                    accessibleLabel={`${att.bestandsnaam} downloaden`}
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => window.open(getTaskAttachmentDownloadUrl(taskId, att.id), '_blank')}
                  />
                  <NlddIconButton
                    icon="trash"
                    accessibleLabel={`${att.bestandsnaam} verwijderen`}
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => setWeg(att)}
                  />
                </nldd-container>
              </nldd-list-item>
            ))}
          </nldd-list>
        )}
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <div className="row-fill">{acties}</div>
          <NlddButton variant="neutral-transparent" size="sm" startIcon="upload" onClick={() => fileInputRef.current?.click()} loading={upload.isPending} text="Uploaden" />
          <input type="file" multiple hidden ref={fileInputRef} onChange={onFiles} />
        </nldd-container>
      </nldd-container>
      <ConfirmDialog
        open={!!weg}
        onClose={() => setWeg(null)}
        onConfirm={verwijder}
        title="Bestand verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={remove.isPending}
      >
        {`"${weg?.bestandsnaam ?? ''}" wordt definitief verwijderd.`}
      </ConfirmDialog>
    </div>
  );
}
