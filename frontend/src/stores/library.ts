import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { explorationClient } from "../api/explorationClient";
import type { GraphPathView, GraphView, LibraryOverview, ResourceDetail } from "../domain/exploration";
import { useAgentWorkspaceStore } from "./agentWorkspace";

type ReadOptions = { maxAttempts?: number };
type OverviewReadOptions = ReadOptions & { force?: boolean };

const DEFAULT_MAX_ATTEMPTS = 2;
const MAX_ALLOWED_ATTEMPTS = 3;
const RETRY_DELAY_MS = 350;

function boundedAttempts(value: number | undefined): number {
  if (!Number.isFinite(value)) return DEFAULT_MAX_ATTEMPTS;
  return Math.max(1, Math.min(MAX_ALLOWED_ATTEMPTS, Math.floor(value as number)));
}

function retryableReadError(cause: unknown): boolean {
  const message = cause instanceof Error ? cause.message : String(cause ?? "");
  // Contract errors must surface immediately. Only transport failures and
  // explicitly transient HTTP responses receive the small bounded retry.
  return /^EXPLORE_HTTP_(408|425|429|5\d{2})$/.test(message) ||
    /^(failed to fetch|networkerror|fetch failed|network request failed)$/i.test(message);
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function withBoundedRetry<T>(operation: () => Promise<T>, maxAttempts: number): Promise<T> {
  let attempt = 0;
  while (true) {
    try {
      return await operation();
    } catch (cause) {
      attempt += 1;
      if (attempt >= maxAttempts || !retryableReadError(cause)) throw cause;
      await wait(RETRY_DELAY_MS * attempt);
    }
  }
}

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
  const overviewError = ref("");
  const graphError = ref("");
  const graphPathError = ref("");
  const resourceError = ref("");
  const error = computed(() => graphError.value || overviewError.value || graphPathError.value || resourceError.value);

  async function loadOverview(options: OverviewReadOptions = {}): Promise<void> {
    if ((overview.value && !options.force) || loadingOverview.value) return;
    loadingOverview.value = true;
    overviewError.value = "";
    try {
      overview.value = await withBoundedRetry(
        () => explorationClient.overview(),
        boundedAttempts(options.maxAttempts),
      );
    }
    catch { overviewError.value = "馆藏数据暂时无法读取。"; }
    finally { loadingOverview.value = false; }
  }

  async function retryOverview(): Promise<void> {
    await loadOverview({ force: true });
  }

  async function searchGraph(query = graphQuery.value, options: ReadOptions = {}): Promise<void> {
    const input = query.trim();
    if (!input) return;
    loadingGraph.value = true;
    graphQuery.value = input;
    graphError.value = "";
    try {
      graph.value = await withBoundedRetry(
        () => explorationClient.graphSearch(input),
        boundedAttempts(options.maxAttempts),
      );
      graphPaths.value = null;
      highlightedPathId.value = null;
    }
    catch (cause) {
      const code = cause instanceof Error && /^[A-Z0-9_]+$/.test(cause.message) ? cause.message : "GRAPH_SEARCH_UNAVAILABLE";
      graphError.value = `知识图谱暂时无法读取（${code}）。`;
    }
    finally { loadingGraph.value = false; }
  }

  async function retryGraph(query = graphQuery.value): Promise<void> {
    await searchGraph(query);
  }

  async function loadGraphPaths(sourceId: string, targetId: string): Promise<void> {
    loadingGraph.value = true;
    graphPathError.value = "";
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
      graphPathError.value = paths.paths.length ? "" : "两个实体之间没有找到 3 跳以内的公开证据路径。";
    } catch (cause) {
      const code = cause instanceof Error && /^[A-Z0-9_]+$/.test(cause.message) ? cause.message : "GRAPH_PATH_UNAVAILABLE";
      graphPathError.value = `多跳证据路径暂时无法读取（${code}）。`;
    }
    finally { loadingGraph.value = false; }
  }
  async function expandNode(entityId: string): Promise<void> {
    loadingGraph.value = true;
    graphError.value = "";
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
    } catch { graphError.value = "节点关系暂时无法展开。"; }
    finally { loadingGraph.value = false; }
  }
  async function openResource(resourceId: number): Promise<void> {
    detailOpen.value = true;
    selectedResource.value = null;
    resourceError.value = "";
    try {
      selectedResource.value = await explorationClient.resource(resourceId);
      await workspace.observe("RESOURCE_OPENED", { resource_id: resourceId, title: selectedResource.value.title, category: selectedResource.value.category_code ?? "" });
    }
    catch { resourceError.value = "图书详情暂时无法读取。"; }
  }

  return {
    overview, graph, graphPaths, highlightedPathId, graphQuery, selectedResource, detailOpen,
    loadingOverview, loadingGraph, overviewError, graphError, graphPathError, resourceError, error,
    loadOverview, retryOverview, searchGraph, retryGraph, expandNode, loadGraphPaths, openResource,
  };
});
