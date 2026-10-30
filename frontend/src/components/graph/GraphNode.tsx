import { memo } from 'react';
import { Handle, Position } from 'reactflow';
import type { NodeProps } from 'reactflow';
import { NODE_TYPE_COLORS, NodeType, nodeTypeColor } from '@/types';
import { Badge } from '@/components/common/Badge';
import { useVocabulary } from '@/contexts/VocabularyContext';

export interface GraphNodeData {
  label: string;
  description?: string;
  nodeType: NodeType;
  onClick?: () => void;
}

function GraphNodeComponent({ data }: NodeProps<GraphNodeData>) {
  const { nodeLabel } = useVocabulary();
  const color = nodeTypeColor(data.nodeType);
  const label = nodeLabel(data.nodeType);

  return (
    <div
      onClick={data.onClick}
      style={{
        background: 'var(--semantics-surfaces-base-background-color)',
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
        // The type color at 20%: a var() takes no hex alpha suffix, so mix instead.
        border: `1px solid color-mix(in oklch, ${color} 20%, transparent)`,
        minWidth: '180px',
        maxWidth: '240px',
        cursor: 'pointer',
        overflow: 'hidden',
      }}
    >
      {/* Colored top bar; the frame's overflow clips it to the corners. */}
      <div style={{ height: '4px', background: color }} />

      <nldd-container gap="6" padding-block="10" padding-inline="12">
        <div className="hug">
          <Badge color={NODE_TYPE_COLORS[data.nodeType] ?? 'coolgray'}>{label}</Badge>
        </div>
        <nldd-text size="sm" weight="medium" className="line-clamp-2">
          {data.label}
        </nldd-text>
      </nldd-container>

      <Handle
        type="target"
        position={Position.Top}
        style={{
          width: '8px',
          height: '8px',
          background: color,
          border: '2px solid var(--semantics-surfaces-base-background-color)',
          top: '-4px',
        }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          width: '8px',
          height: '8px',
          background: color,
          border: '2px solid var(--semantics-surfaces-base-background-color)',
          bottom: '-4px',
        }}
      />
    </div>
  );
}

export const GraphNode = memo(GraphNodeComponent);
