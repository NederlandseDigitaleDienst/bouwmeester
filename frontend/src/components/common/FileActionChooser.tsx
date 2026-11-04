import { Modal } from './Modal';
import { NlddListItemButton } from '@/components/nldd/NlddLink';
import { useGlobalFileDropContext } from '@/hooks/useGlobalFileDropContext';
import { NlddButton } from '@/components/nldd/NlddButton';

/** One of the things you can do with the dropped file. */
function ActionRow({
  icon,
  title,
  description,
  onSelect,
}: {
  icon: string;
  title: string;
  description: string;
  onSelect: () => void;
}) {
  return (
    <NlddListItemButton onClick={onSelect}>
      <nldd-icon-cell icon={icon} size="24" color="accent" />
      <nldd-text-cell text={title} supporting-text={description} />
    </NlddListItemButton>
  );
}

export function FileActionChooser() {
  const { chooserFiles, showChooser, setShowChooser, chooseAction, discardChooserFiles } =
    useGlobalFileDropContext();

  if (!showChooser || chooserFiles.length === 0) return null;

  const handleClose = () => {
    setShowChooser(false);
    discardChooserFiles();
  };

  const fileLabel =
    chooserFiles.length === 1 ? chooserFiles[0].name : `${chooserFiles.length} bestanden`;

  return (
    <Modal open={showChooser} onClose={handleClose} title="Bestand ontvangen" size="sm">
      <nldd-container gap="16">
        {/* What was dropped. A banner rather than a tinted strip: it reports
            something that just happened, which is what a banner is for. */}
        <nldd-banner variant="neutral" icon="file-text" text={fileLabel} size="sm" />

        <nldd-text size="sm" color="secondary">
          Wat wil je met dit bestand doen?
        </nldd-text>

        {/* Two choices, so a list of rows rather than two buttons carrying a
            title and a description each. The row is the control; the cells set
            the type scale and the alignment against the row height. */}
        <nldd-list appearance="simple" accessible-label="Wat wil je met dit bestand doen?">
          <ActionRow
            icon="users"
            title="Nieuwe lead aanmaken"
            description="Analyseer met VLAM en maak een lead aan"
            onSelect={() => chooseAction('lead')}
          />
          <ActionRow
            icon="book"
            title="Bron toevoegen aan corpus"
            description="Voeg toe als bronbestand"
            onSelect={() => chooseAction('bron')}
          />
        </nldd-list>

        <nldd-container horizontal-alignment="right">
          <NlddButton variant="neutral-transparent" onClick={handleClose} text="Annuleren" />
        </nldd-container>
      </nldd-container>
    </Modal>
  );
}
