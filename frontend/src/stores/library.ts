import { ref } from "vue";
import { defineStore } from "pinia";

import { explorationClient } from "../api/explorationClient";
import type { GraphPathView, GraphView, LibraryOverview, ResourceDetail } from "../domain/exploration";
import { useAgentWorkspaceStore } from "./agentWorkspace";

export const useLibraryStore = defineStore("library", () => {
  const workspace = useAgentWorkspaceStore();
  const overview = ref<LibraryOverview | null>(null);
  const graph = ref<GraphView | null>(null);
  const graphPaths = ref<GraphPathView | null>(null);
  const highlightedPathId = ref<string | null>(null);
  const graphQuery = ref("人工智能");
  const selectedResource = ref<ResourceDetail | null>(null);
  const detailOpen = ref(false);
  const loadingOverview = ref(false);
  const loadingGraph = ref(false);
  const error = ref("");

  async function loadOverview(): Promise<void> {
    if (overview.value || loadingOverview.value) return;
    loadingOverview.value = true;
    try { overview.value = await explorationClient.overview(); error.value = ""; }
    catch { error.value = "馆藏数据暂时无法读取。"; }
    finally { loadingOverview.value = false; }
  }
  async function searchGraph(query = graphQuery.value): Promise<void> {
    const input = query.trim();
    if (!input) return;
    loadingGraph.value = true;
    graphQuery.value = input;
    try { graph.value = await explorationClient.graphSearch(input); graphPaths.value = null; highlightedPathId.value = null; error.value = ""; }
    catch { error.value = "知识图谱暂时无法读取。"; }
    finally { loadingGraph.value = false; }
  }
  async function loadGraphPaths(sourceId: string, targetId: string): Promise<void> {
    loadingGraph.value = true;
    try {
      const paths = await explorationClient.graphPaths(sourceId, targetId, 3, 10);
      graphPaths.value = paths;
      highlightedPathId.value = paths.paths[0]?.path_id ?? null;
      const nodes = new Map((graph.value?.nodes ?? []).map((node) => [node.id, node]));
      const edges = new Map((graph.value?.edges ?? []).map((edge) => [edge.id, edge]));
      paths.graph.nodes.forEach((node) => nodes.set(node.id, node));
      paths.graph.edges.forEach((edge) => edges.set(edge.id, edge));
      graph.value = {
        graph_version: paths.graph_version,
        query: `${sourceId} → ${targetId}`,
        nodes: [...nodes.values()].slice(0, 60),
        edges: [...edges.values()].slice(0, 120),
        truncated: Boolean(graph.value?.truncated || paths.truncated),
      };
      error.value = paths.paths.length ? "" : "两个实体之间没有找到 3 跳以内的公开证据路径。";
    } catch { error.value = "多跳证据路径暂时无法读取。"; }
    finally { loadingGraph.value = false; }
  }
  async function expandNode(entityId: string): Promise<void> {
    loadingGraph.value = true;
    try {
      const next = await explorationClient.graphNeighbors(entityId);
      if (!graph.value) graph.value = next;
      else {
        const nodes = new Map(graph.value.nodes.map((node) => [node.id, node]));
        const edges = new Map(graph.value.edges.map((edge) => [edge.id, edge]));
        next.nodes.forEach((node) => nodes.set(node.id, node));
        next.edges.forEach((edge) => edges.set(edge.id, edge));
        graph.value = { ...graph.value, nodes: [...nodes.values()].slice(0, 60), edges: [...edges.values()].slice(0, 120), truncated: graph.value.truncated || next.truncated };
      }
    } catch { error.value = "节点关系暂时无法展开。"; }
    finally { loadingGraph.value = false; }
  }
  async function openResource(resourceId: number): Promise<void> {
    detailOpen.value = true;
    selectedResource.value = null;
    try {
      selectedResource.value = await explorationClient.resource(resourceId);
      await workspace.observe("RESOURCE_OPENED", { resource_id: resourceId, title: selectedResource.value.title, category: selectedResource.value.category_code ?? "" });
    }
    catch { error.value = "图书详情暂时无法读取。"; }
  }

  return { overview, graph, graphPaths, highlightedPathId, graphQuery, selectedResource, detailOpen, loadingOverview, loadingGraph, error, loadOverview, searchGraph, expandNode, loadGraphPaths, openResource };
});
