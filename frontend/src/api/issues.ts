import { apiGet, apiPost, apiPut, apiDelete } from './client';
import type { Issue, IssueCreate, IssueUpdate } from '@/types';

export async function getIssues(casusId: string): Promise<Issue[]> {
  return apiGet<Issue[]>(`/api/casussen/${casusId}/issues`);
}

export async function createIssue(casusId: string, data: IssueCreate): Promise<Issue> {
  return apiPost<Issue>(`/api/casussen/${casusId}/issues`, data);
}

export async function updateIssue(casusId: string, issueId: string, data: IssueUpdate): Promise<Issue> {
  return apiPut<Issue>(`/api/casussen/${casusId}/issues/${issueId}`, data);
}

export async function deleteIssue(casusId: string, issueId: string): Promise<void> {
  return apiDelete(`/api/casussen/${casusId}/issues/${issueId}`);
}
