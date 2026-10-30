import { TaskDetailModal } from '@/components/tasks/TaskDetailModal';
import { NodeDetailModal } from '@/components/nodes/NodeDetailModal';
import { OpdrachtDetailModal } from '@/components/opdrachten/OpdrachtDetailModal';
import { OpdrachtCreateModal } from '@/components/opdrachten/OpdrachtCreateModal';
import { LeadDetailPanel } from '@/components/leads/LeadDetailPanel';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useOpdrachtDetail } from '@/contexts/OpdrachtDetailContext';
import { useLeadDetail } from '@/contexts/LeadDetailContext';


/**
 * The four detail surfaces, mounted once and driven by their contexts.
 *
 * Stacking is the browser's. These are native `<dialog>` elements, so the last
 * one opened is on top by definition, including when one is re-opened from
 * underneath another.
 */
export function DetailModals() {
  const { taskDetailId, taskDetailPlacement, closeTaskDetail } = useTaskDetail();
  const { nodeDetailId, closeNodeDetail } = useNodeDetail();
  const { opdrachtDetailId, closeOpdrachtDetail } = useOpdrachtDetail();
  const { leadDetailId, closeLeadDetail } = useLeadDetail();

  // No stacking order is computed here. `nldd-window` is a native `<dialog>`,
  // so the browser's top layer decides: the last one opened is on top, by
  // definition.
  //
  // The `*OpenSeq` values the contexts expose have no reader left; they can go
  // whenever the contexts themselves are touched.

  return (
    <>
      <OpdrachtCreateModal />
      <OpdrachtDetailModal
        opdrachtId={opdrachtDetailId}
        open={!!opdrachtDetailId}
        onClose={closeOpdrachtDetail}
      />
      <NodeDetailModal
        nodeId={nodeDetailId}
        open={!!nodeDetailId}
        onClose={closeNodeDetail}
      />
      <TaskDetailModal
        taskId={taskDetailId}
        open={!!taskDetailId}
        onClose={closeTaskDetail}
        placement={taskDetailPlacement}
      />
      <LeadDetailPanel
        leadId={leadDetailId}
        open={!!leadDetailId}
        onClose={closeLeadDetail}
      />
    </>
  );
}
