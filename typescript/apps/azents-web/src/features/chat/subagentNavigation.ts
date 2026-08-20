export interface SubagentNavigationNode {
  session_agent_id: string;
  agent_session_id: string;
  parent_session_agent_id?: string | null;
  name: string;
  path: string;
  children?: SubagentNavigationNode[] | null;
}

export interface SubagentNavigationTree {
  nodes: SubagentNavigationNode[];
  current_session_agent_id: string | null;
  root_session_agent_id: string | null;
}

export interface SubagentNavigationLinks {
  currentName: string;
  currentPath: string;
  parent: SubagentNavigationNode;
  root: SubagentNavigationNode;
}

function flattenSubagentNodes(
  nodes: SubagentNavigationNode[],
): SubagentNavigationNode[] {
  return nodes.flatMap((node) => [
    node,
    ...flattenSubagentNodes(node.children ?? []),
  ]);
}

function findSubagentNode(
  nodes: SubagentNavigationNode[],
  sessionAgentId: string | null,
): SubagentNavigationNode | null {
  if (sessionAgentId === null) {
    return null;
  }
  return nodes.find((node) => node.session_agent_id === sessionAgentId) ?? null;
}

export function resolveSubagentNavigation(
  tree: SubagentNavigationTree,
): SubagentNavigationLinks | null {
  const nodes = flattenSubagentNodes(tree.nodes);
  const current = findSubagentNode(nodes, tree.current_session_agent_id);
  const root = findSubagentNode(nodes, tree.root_session_agent_id);
  const parent = findSubagentNode(
    nodes,
    current?.parent_session_agent_id ?? null,
  );
  if (
    current === null ||
    root === null ||
    parent === null ||
    current.session_agent_id === root.session_agent_id
  ) {
    return null;
  }
  return {
    currentName: current.name,
    currentPath: current.path,
    parent,
    root,
  };
}
