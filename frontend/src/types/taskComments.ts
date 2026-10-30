/**
 * Opmerkingen en bijlagen op een taak (het taakdetail). Eigen bestand naast
 * index.ts; wordt daar opnieuw geëxporteerd.
 */

export interface TaskComment {
  id: string;
  task_id: string;
  author_id: string | null;
  author_naam: string | null;
  content: string;
  created_at: string;
  updated_at?: string | null;
}

export interface TaskCommentCreate {
  content: string;
}

export interface TaskAttachment {
  id: string;
  task_id: string;
  bestandsnaam: string;
  content_type: string | null;
  bestandsgrootte: number | null;
  created_at: string;
}
