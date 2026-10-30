import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getTasks,
  getTask,
  createTask,
  updateTask,
  deleteTask,
  getEenheidOverview,
  getTasksByPerson,
  reorderSubtasks,
  getWorkTypes,
  getTasksByOpdracht,
  getTaskComments,
  createTaskComment,
  deleteTaskComment,
  getTaskAttachments,
  uploadTaskAttachment,
  deleteTaskAttachment,
} from '@/api/tasks';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import { queryKeys } from '@/hooks/queryKeys';
import { useToast } from '@/contexts/ToastContext';
import type { Task, TaskCreate, TaskUpdate, TaskFilters } from '@/types';
import type { TaskCommentCreate } from '@/types/taskComments';

export function useTasks(filters?: TaskFilters) {
  return useQuery({
    queryKey: queryKeys.tasks.list(filters),
    queryFn: () => getTasks(filters),
  });
}

export function useTask(id: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.detail(id),
    queryFn: () => getTask(id!),
    enabled: !!id,
  });
}

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutationWithError({
    mutationFn: (data: TaskCreate) => createTask(data),
    errorMessage: 'Fout bij aanmaken taak',
    invalidateKeys: [queryKeys.tasks.lists(), queryKeys.tasks.workTypes()],
    // Een nieuwe subtaak staat in het detail van haar hoofdtaak.
    onSuccess: (_task, data) => {
      if (data.parent_id) void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(data.parent_id) });
    },
  });
}

export function useUpdateTask() {
  const queryClient = useQueryClient();
  return useMutationWithError({
    mutationFn: ({ id, data }: { id: string; data: TaskUpdate }) => updateTask(id, data),
    errorMessage: 'Fout bij bijwerken taak',
    invalidateKeys: [queryKeys.tasks.lists(), queryKeys.tasks.workTypes()],
    // De taak zelf ook. Zonder dit houdt het taakdetail de oude versie vast en
    // springt een keuzelijst daar na een wijziging terug naar de oude waarde.
    onSuccess: (task, { id }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(id) });
      // Een afgevinkte subtaak staat ook in het detail van haar hoofdtaak.
      if (task?.parent_id) void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(task.parent_id) });
    },
  });
}

export function useDeleteTask() {
  return useMutationWithError({
    mutationFn: (id: string) => deleteTask(id),
    errorMessage: 'Fout bij verwijderen taak',
    // Ook de details: een verwijderde subtaak staat in die van haar hoofdtaak.
    invalidateKeys: [queryKeys.tasks.lists(), queryKeys.tasks.details()],
  });
}

export function useEenheidOverview(organisatieEenheidId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.eenheidOverview(organisatieEenheidId),
    queryFn: () => getEenheidOverview(organisatieEenheidId!),
    enabled: !!organisatieEenheidId,
  });
}

export function useTasksByPerson(personId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.byPerson(personId),
    queryFn: () => getTasksByPerson(personId!),
    enabled: !!personId,
  });
}

export function useTasksByOpdracht(opdrachtId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.byOpdracht(opdrachtId),
    queryFn: () => getTasksByOpdracht(opdrachtId!),
    enabled: !!opdrachtId,
  });
}

export function useWorkTypes() {
  return useQuery({
    queryKey: queryKeys.tasks.workTypes(),
    queryFn: getWorkTypes,
  });
}

export function useReorderSubtasks() {
  const queryClient = useQueryClient();
  const { showError } = useToast();

  return useMutation({
    mutationFn: ({ taskId, taskIds }: { taskId: string; taskIds: string[] }) =>
      reorderSubtasks(taskId, taskIds),
    onMutate: async ({ taskId, taskIds }) => {
      // Cancel outgoing refetches so they don't overwrite optimistic update
      await queryClient.cancelQueries({ queryKey: queryKeys.tasks.detail(taskId) });

      const previousTask = queryClient.getQueryData<Task>(queryKeys.tasks.detail(taskId));

      if (previousTask?.subtasks) {
        const subtaskMap = new Map(previousTask.subtasks.map((s) => [s.id, s]));
        const reorderedSubtasks = taskIds
          .map((id) => subtaskMap.get(id))
          .filter(Boolean);

        queryClient.setQueryData(queryKeys.tasks.detail(taskId), {
          ...previousTask,
          subtasks: reorderedSubtasks,
        });
      }

      return { previousTask, taskId };
    },
    onError: (error, _variables, context) => {
      // Roll back to previous state
      if (context?.previousTask) {
        queryClient.setQueryData(
          queryKeys.tasks.detail(context.taskId),
          context.previousTask,
        );
      }
      console.error('Fout bij herordenen subtaken:', error);
      showError('Fout bij herordenen subtaken');
    },
    onSettled: (_data, _error, variables) => {
      // Refetch to ensure server state is authoritative
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(variables.taskId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.lists() });
    },
  });
}

// --- Opmerkingen en bijlagen (het taakdetail) ---

export function useTaskComments(taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.comments(taskId),
    queryFn: () => getTaskComments(taskId!),
    enabled: !!taskId,
  });
}

export function useAddTaskComment() {
  return useMutationWithError({
    mutationFn: ({ taskId, data }: { taskId: string; data: TaskCommentCreate }) => createTaskComment(taskId, data),
    errorMessage: 'Fout bij plaatsen opmerking',
    invalidateKeys: [queryKeys.tasks.all],
  });
}

export function useDeleteTaskComment() {
  return useMutationWithError({
    mutationFn: ({ taskId, commentId }: { taskId: string; commentId: string }) => deleteTaskComment(taskId, commentId),
    errorMessage: 'Fout bij verwijderen opmerking',
    invalidateKeys: [queryKeys.tasks.all],
  });
}

export function useTaskAttachments(taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.attachments(taskId),
    queryFn: () => getTaskAttachments(taskId!),
    enabled: !!taskId,
  });
}

export function useUploadTaskAttachment() {
  return useMutationWithError({
    mutationFn: ({ taskId, file }: { taskId: string; file: File }) => uploadTaskAttachment(taskId, file),
    errorMessage: 'Fout bij uploaden bijlage',
    invalidateKeys: [queryKeys.tasks.all],
  });
}

export function useDeleteTaskAttachment() {
  return useMutationWithError({
    mutationFn: ({ taskId, attachmentId }: { taskId: string; attachmentId: string }) =>
      deleteTaskAttachment(taskId, attachmentId),
    errorMessage: 'Fout bij verwijderen bijlage',
    invalidateKeys: [queryKeys.tasks.all],
  });
}
