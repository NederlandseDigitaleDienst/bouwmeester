/** Een bestandsgrootte zoals mensen hem lezen: "120 KB", "2,4 MB". */
export function bestandsgrootte(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString('nl-NL', { maximumFractionDigits: 1 })} MB`;
}
