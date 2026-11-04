import { apiGet, apiPost, apiPut, apiDelete, getCsrfToken, BASE_URL } from './client';
import type { Task, TaskCreate, TaskUpdate, EenheidOverviewResponse, TaskFilters } from '@/types';
import type { TaskAttachment, TaskComment, TaskCommentCreate } from '@/types/taskComments';

export async function getTasks(filters?: TaskFilters): Promise<Task[]> {
  return apiGet<Task[]>('/api/tasks', filters as Record<string, string>);
}

export async function getTask(id: string): Promise<Task> {
  return apiGet<Task>(`/api/tasks/${id}`);
}

export async function createTask(data: TaskCreate): Promise<Task> {
  return apiPost<Task>('/api/tasks', data);
}

export async function updateTask(id: string, data: TaskUpdate): Promise<Task> {
  return apiPut<Task>(`/api/tasks/${id}`, data);
}

export async function deleteTask(id: string): Promise<void> {
  return apiDelete(`/api/tasks/${id}`);
}

export async function getEenheidOverview(organisatieEenheidId: string): Promise<EenheidOverviewResponse> {
  return apiGet<EenheidOverviewResponse>('/api/tasks/eenheid-overview', {
    organisatie_eenheid_id: organisatieEenheidId,
  });
}

export async function getTasksByPerson(personId: string): Promise<Task[]> {
  return apiGet<Task[]>('/api/tasks', { assignee_id: personId });
}

export async function reorderSubtasks(taskId: string, taskIds: string[]): Promise<Task[]> {
  return apiPut<Task[]>(`/api/tasks/${taskId}/subtasks/reorder`, { task_ids: taskIds });
}

export async function getWorkTypes(): Promise<string[]> {
  return apiGet<string[]>('/api/tasks/work-types');
}

export async function getTasksByOpdracht(opdrachtId: string): Promise<Task[]> {
  return apiGet<Task[]>('/api/tasks', { opdracht_id: opdrachtId });
}

// --- Opmerkingen en bijlagen (het taakdetail) ---

export async function getTaskComments(taskId: string): Promise<TaskComment[]> {
  return apiGet<TaskComment[]>(`/api/tasks/${taskId}/comments`);
}

export async function createTaskComment(taskId: string, data: TaskCommentCreate): Promise<TaskComment> {
  return apiPost<TaskComment>(`/api/tasks/${taskId}/comments`, data);
}

export async function deleteTaskComment(taskId: string, commentId: string): Promise<void> {
  return apiDelete(`/api/tasks/${taskId}/comments/${commentId}`);
}

export async function getTaskAttachments(taskId: string): Promise<TaskAttachment[]> {
  return apiGet<TaskAttachment[]>(`/api/tasks/${taskId}/attachments`);
}

/** Zelfde opzet als uploadLeadAttachment: multipart, dus niet via apiPost. */
export async function uploadTaskAttachment(taskId: string, file: File): Promise<TaskAttachment> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${BASE_URL}/api/tasks/${taskId}/attachments`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': getCsrfToken() },
    body: formData,
    credentials: 'include',
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Upload failed: ${response.status} ${text}`);
  }
  return response.json();
}

export async function deleteTaskAttachment(taskId: string, attachmentId: string): Promise<void> {
  return apiDelete(`/api/tasks/${taskId}/attachments/${attachmentId}`);
}

export function getTaskAttachmentDownloadUrl(taskId: string, attachmentId: string): string {
  return `${BASE_URL}/api/tasks/${taskId}/attachments/${attachmentId}/download`;
}
