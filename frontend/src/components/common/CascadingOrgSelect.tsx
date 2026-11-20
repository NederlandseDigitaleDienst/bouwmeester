import { useState, useEffect, useMemo } from 'react';
import { useOrganisatieTree, useCreateOrganisatieEenheid } from '@/hooks/useOrganisatie';
import { formatOrganisatieType } from '@/types';
import type { OrganisatieEenheidTreeNode } from '@/types';
import { CreatableSelect } from './CreatableSelect';
import type { SelectOption } from './CreatableSelect';
import { LoadingSpinner } from './LoadingSpinner';

interface CascadingOrgSelectProps {
  value: string;
  onChange: (id: string) => void;
  label?: string;
  allowCreate?: boolean;
  /** Minimum number of levels the user must select before the value is emitted. Default: 1 */
  minDepth?: number;
}

/** Default child type when creating under a parent of a given type. */
const DEFAULT_CHILD_TYPE: Record<string, string> = {
  ministerie: 'directoraat_generaal',
  directoraat_generaal: 'directie',
  directie: 'afdeling',
  afdeling: 'team',
  dienst: 'bureau',
  bureau: 'team',
  cluster: 'team',
};

/** Root-level default when creating with no parent. */
const ROOT_DEFAULT_TYPE = 'ministerie';

/**
 * Infer the type for a new child org unit.
 * Prefers most-common sibling type when siblings exist, otherwise uses
 * DEFAULT_CHILD_TYPE mapping from parent.
 */
function inferChildType(
  parentType: string | null,
  siblings: OrganisatieEenheidTreeNode[],
): string {
  if (siblings.length > 0) {
    // Use the most common type among siblings
    const counts: Record<string, number> = {};
    for (const s of siblings) {
      counts[s.type] = (counts[s.type] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  }
  if (parentType) {
    return DEFAULT_CHILD_TYPE[parentType] || 'afdeling';
  }
  return ROOT_DEFAULT_TYPE;
}

/**
 * Find the path of node IDs from root to a target node in the tree.
 * Returns an array of IDs: [rootId, childId, ..., targetId].
 */
function findPathToNode(
  nodes: OrganisatieEenheidTreeNode[],
  targetId: string,
): string[] {
  for (const node of nodes) {
    if (node.id === targetId) return [node.id];
    if (node.children.length > 0) {
      const childPath = findPathToNode(node.children, targetId);
      if (childPath.length > 0) return [node.id, ...childPath];
    }
  }
  return [];
}

export function CascadingOrgSelect({
  value,
  onChange,
  label = 'Organisatie-eenheid',
  allowCreate = true,
  minDepth = 1,
}: CascadingOrgSelectProps) {
  const { data: tree = [], isLoading } = useOrganisatieTree();
  const [selections, setSelections] = useState<string[]>([]);
  const createMutation = useCreateOrganisatieEenheid();

  // When value changes externally (or on mount), rebuild the path
  useEffect(() => {
    setSelections((prev) => {
      if (!value || tree.length === 0) {
        return prev.length === 0 ? prev : [];
      }
      const path = findPathToNode(tree, value);
      if (path.length === 0) return prev;
      // Only update if the path actually changed
      if (
        prev.length === path.length &&
        prev.every((s, i) => s === path[i])
      ) {
        return prev;
      }
      return path;
    });
  }, [value, tree]);

  // Build levels: each level has options and a selected value
  const levels = useMemo(() => {
    const result: {
      options: OrganisatieEenheidTreeNode[];
      selected: string;
      type: string;
      parentType: string | null;
    }[] = [];
    let currentNodes = tree;

    for (const sel of selections) {
      const typeLabel =
        currentNodes.length > 0
          ? formatOrganisatieType(currentNodes[0].type)
          : '';
      const parentType =
        currentNodes.length > 0 ? currentNodes[0].type : null;
      result.push({
        options: currentNodes,
        selected: sel,
        type: typeLabel,
        parentType,
      });
      const node = currentNodes.find((n) => n.id === sel);
      currentNodes = node?.children || [];
    }

    // Add the next level if there are children to pick from,
    // OR if allowCreate is enabled (so user can create first child under a leaf)
    if (currentNodes.length > 0 || (allowCreate && selections.length > 0)) {
      const typeLabel =
        currentNodes.length > 0
          ? formatOrganisatieType(currentNodes[0].type)
          : '';
      const parentType =
        currentNodes.length > 0 ? currentNodes[0].type : null;
      result.push({
        options: currentNodes,
        selected: '',
        type: typeLabel,
        parentType,
      });
    }

    return result;
  }, [tree, selections, allowCreate]);

  const handleChange = (levelIndex: number, nodeId: string) => {
    const newSelections = selections.slice(0, levelIndex);
    if (nodeId) {
      newSelections.push(nodeId);
    }
    setSelections(newSelections);
    const deepestId =
      newSelections.length > 0 ? newSelections[newSelections.length - 1] : '';
    // Only emit a value when the user has drilled deep enough
    onChange(newSelections.length >= minDepth ? deepestId : '');
  };

  const showDepthHint =
    minDepth > 1 && selections.length > 0 && selections.length < minDepth;

  const handleCreate = async (
    levelIndex: number,
    naam: string,
  ): Promise<string | null> => {
    const parentId =
      levelIndex > 0 ? selections[levelIndex - 1] : undefined;

    // Look up parent type from previous level
    const parentLevel = levelIndex > 0 ? levels[levelIndex - 1] : null;
    const parentNode = parentLevel
      ? parentLevel.options.find((n) => n.id === parentId)
      : null;
    const parentType = parentNode?.type || null;

    const siblings = levels[levelIndex]?.options || [];
    const type = inferChildType(parentType, siblings);

    const result = await createMutation.mutateAsync({
      naam,
      type,
      parent_id: parentId || null,
    });

    if (result?.id) {
      // Optimistically update selections
      const newSelections = selections.slice(0, levelIndex);
      newSelections.push(result.id);
      setSelections(newSelections);
      onChange(newSelections.length >= minDepth ? result.id : '');
      return result.id;
    }
    return null;
  };

  if (isLoading) {
    return (
      <nldd-container gap="4">
        {label && (
          <nldd-text size="sm" weight="bold">
            <p>
              {label}
            </p>
          </nldd-text>
        )}
        <LoadingSpinner size="sm" />
      </nldd-container>
    );
  }

  if (tree.length === 0 && !allowCreate) return null;

  return (
    <nldd-container gap="4">
      {/* Not an nldd-form-field: that labels ONE control, and this renders a
          chain of them (ministerie, directie, afdeling...) that grows as you
          pick. The label names the group, so it is a heading for the set. */}
      {label && (
        <nldd-text size="sm" weight="bold">
          <p>
            {label}
          </p>
        </nldd-text>
      )}
      <nldd-container gap="8">
        {levels.map((level, i) => {
          const selectOptions: SelectOption[] = level.options.map((node) => ({
            value: node.id,
            label: node.naam,
            description: formatOrganisatieType(node.type),
          }));

          const placeholder = level.type
            ? `Kies ${level.type.toLowerCase()}...`
            : 'Kies eenheid...';

          return (
            <CreatableSelect
              key={`${i}-${level.type}`}
              value={level.selected}
              onChange={(val) => handleChange(i, val)}
              options={selectOptions}
              placeholder={placeholder}
              onCreate={
                allowCreate
                  ? (text) => handleCreate(i, text)
                  : undefined
              }
              createLabel="Nieuwe eenheid aanmaken"
            />
          );
        })}
        {showDepthHint && (
          <nldd-text size="xs" color="warning">
            <p>Kies een specifiekere organisatie-eenheid</p>
          </nldd-text>
        )}
      </nldd-container>
    </nldd-container>
  );
}
