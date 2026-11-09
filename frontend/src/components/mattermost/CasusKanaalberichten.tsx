import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { Icon } from '@/components/nldd/Icon';
import { useCasusKanaalberichten } from '@/hooks/useMattermostChannels';
import type { CasusKanaalbericht } from '@/api/mattermostChannels';
import { formatDateTimeShort } from '@/utils/dates';

// De shortcodes die de berichten gebruiken, zoals Mattermost ze laat zien.
const EMOJI: Record<string, string> = {
  ':arrow_right:': '➡️',
  ':new:': '🆕',
  ':white_check_mark:': '✅',
};

function metEmoji(tekst: string): string {
  return tekst.replace(/:[a-z_]+:/g, (code) => EMOJI[code] ?? code);
}

function statusTekst(bericht: CasusKanaalbericht): string {
  const naar = bericht.kanalen.join(', ');
  switch (bericht.status) {
    case 'geen_kanaal':
      return 'Alleen hier: geen kanaal met voortgang aan';
    case 'wacht':
      return `Wordt verstuurd naar ${naar}`;
    case 'verstuurd':
      return `Verstuurd naar ${naar}`;
    case 'mislukt':
      return `Niet in elk kanaal gelukt: ${naar}`;
    case 'uit':
      return `Niet verstuurd naar ${naar}: Mattermost stond uit`;
  }
}

/**
 * Wat Bouwmeester over deze casus in het kanaal zet, zoals het daar staat.
 * Ook de berichten zonder kanaal of met Mattermost uit: zo is te zien wat
 * het kanaal zou krijgen.
 */
export function CasusKanaalberichten({ casusId }: { casusId: string }) {
  const { data, isLoading, isError } = useCasusKanaalberichten(casusId);

  return (
    <nldd-card>
      <nldd-container gap="12" padding="16">
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          <Icon name="message-rectangle-text" size="sm" />
          <nldd-text size="xs" weight="bold" color="secondary">
            Berichten voor het kanaal
          </nldd-text>
        </nldd-container>

        {isLoading && (
          <nldd-container padding-block="24">
            <LoadingSpinner />
          </nldd-container>
        )}
        {isError && <nldd-inline-dialog variant="alert" size="md" text="Kon de berichten niet ophalen." />}
        {data && data.length === 0 && (
          <nldd-inline-dialog
            text="Nog geen berichten."
            supporting-text="Er komt een bericht bij een andere fase en bij een nieuwe of afgeronde onderzoeksvraag."
          />
        )}
        {data && data.length > 0 && (
          <nldd-list type="list" appearance="box-tinted" accessible-label="Berichten voor het kanaal">
            {data.map((bericht) => (
              <nldd-list-item key={bericht.id}>
                <nldd-container width="full" min-width="0" gap="4" padding="4">
                  <MarkdownRenderer content={metEmoji(bericht.tekst)} compact />
                  <nldd-text size="xs" color="secondary">
                    {formatDateTimeShort(bericht.created_at)} · {statusTekst(bericht)}
                  </nldd-text>
                </nldd-container>
              </nldd-list-item>
            ))}
          </nldd-list>
        )}
      </nldd-container>
    </nldd-card>
  );
}
