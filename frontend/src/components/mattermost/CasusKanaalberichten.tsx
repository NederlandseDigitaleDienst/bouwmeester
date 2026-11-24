import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { Icon } from '@/components/nldd/Icon';
import { NlddButton } from '@/components/nldd/NlddButton';
import { useCasusKanaalberichten, useOpnieuwCasusKanaalbericht } from '@/hooks/useMattermostChannels';
import type { CasusKanaalbericht } from '@/api/mattermostChannels';
import { formatDateTimeShort } from '@/utils/dates';

// De shortcodes die de berichten gebruiken, zoals Mattermost ze laat zien.
const EMOJI: Record<string, string> = {
  ':arrow_right:': '➡️',
  ':new:': '🆕',
  ':white_check_mark:': '✅',
};

// Na zo lang is "wacht" niet meer onderweg maar blijven hangen; de worker
// pakt het dan op, en wie mag, kan het zelf opnieuw doen.
const BLIJFT_HANGEN_NA_MS = 10 * 60_000;

function metEmoji(tekst: string): string {
  return tekst.replace(/:[a-z_]+:/g, (code) => EMOJI[code] ?? code);
}

function blijftHangen(bericht: CasusKanaalbericht): boolean {
  return bericht.status === 'wacht' && Date.now() - Date.parse(bericht.created_at) > BLIJFT_HANGEN_NA_MS;
}

/** Niet (zeker) aangekomen: dan mag het nog een keer. */
function kanOpnieuw(bericht: CasusKanaalbericht): boolean {
  return bericht.status === 'mislukt' || bericht.status === 'uit' || blijftHangen(bericht);
}

function statusTekst(bericht: CasusKanaalbericht): string {
  const naar = bericht.kanalen.join(', ');
  switch (bericht.status) {
    case 'geen_kanaal':
      return 'Alleen hier: geen kanaal met voortgang aan';
    case 'wacht':
      return blijftHangen(bericht) ? `Nog niet verstuurd naar ${naar}` : `Wordt verstuurd naar ${naar}`;
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
 * het kanaal zou krijgen. Wie de casus mag wijzigen, kan een bericht dat
 * niet aankwam opnieuw versturen.
 */
export function CasusKanaalberichten({ casusId, kanBeheren = false }: { casusId: string; kanBeheren?: boolean }) {
  const { data, isLoading, isError } = useCasusKanaalberichten(casusId);
  const opnieuw = useOpnieuwCasusKanaalbericht(casusId);

  return (
    <nldd-card>
      <nldd-container gap="12" padding="16">
        <nldd-container layout="row" gap="6" vertical-alignment="center">
          <Icon name="message-rectangle-text" size="sm" />
          <nldd-text size="xs" weight="medium" color="secondary">
            Berichten voor het kanaal
          </nldd-text>
        </nldd-container>

        {isLoading && (
          <nldd-container padding-block="24">
            <LoadingSpinner />
          </nldd-container>
        )}
        {isError && <nldd-inline-dialog variant="alert" size="md" text="Kon de berichten niet ophalen." />}
        {opnieuw.isError && (
          <nldd-inline-dialog variant="alert" size="md" text="Opnieuw versturen is niet gelukt. Probeer het zo nog eens." />
        )}
        {data && data.length === 0 && (
          <nldd-inline-dialog
            text="Nog geen berichten."
            supporting-text="Er komt een bericht bij een andere fase en bij een nieuw of afgerond issue, onderzoeksvraag of niet."
          />
        )}
        {data && data.length > 0 && (
          <nldd-list type="list" appearance="box-tinted" accessible-label="Berichten voor het kanaal">
            {data.map((bericht) => (
              <nldd-list-item key={bericht.id}>
                <nldd-container width="full" min-width="0" gap="4" padding="4">
                  <MarkdownRenderer content={metEmoji(bericht.tekst)} compact />
                  <nldd-container layout="wrap" gap="8" vertical-alignment="center">
                    <nldd-text size="xs" color="secondary">
                      {formatDateTimeShort(bericht.created_at)} · {statusTekst(bericht)}
                    </nldd-text>
                    {kanBeheren && kanOpnieuw(bericht) && (
                      <NlddButton
                        variant="neutral-transparent"
                        size="sm"
                        startIcon="refresh"
                        text="Opnieuw"
                        disabled={opnieuw.isPending}
                        onClick={() => opnieuw.mutate(bericht.id)}
                      />
                    )}
                  </nldd-container>
                </nldd-container>
              </nldd-list-item>
            ))}
          </nldd-list>
        )}
      </nldd-container>
    </nldd-card>
  );
}
