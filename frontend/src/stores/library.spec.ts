import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { explorationClient } from "../api/explorationClient";
import type { GraphPathView, LibraryOverview } from "../domain/exploration";
import { useLibraryStore } from "./library";

vi.mock("../api/explorationClient", () => ({
  explorationClient: {
    overview: vi.fn(),
    graphSearch: vi.fn(),
    graphNeighbors: vi.fn(),
    graphPaths: vi.fn(),
    resource: vi.fn(),
  },
}));

const overviewFixture: LibraryOverview = {
  schema_version: "exploration-v1",
  dataset_version: "books-test",
  graph_version: "lib-books-v1-20260810",
  generated_at: "2026-09-05T00:00:00.000Z",
  totals: { resources: 2, books: 2, papers: 0, tags: 1 },
  graph: { nodes: 3, relationships: 2 },
  availability: [{ name: "AVAILABLE_BORROW", count: 2 }],
  categories: [{ name: "人工智能", count: 2 }],
  publication_decades: [{ year: 2020, count: 2 }],
  popular_topics: [{ name: "多智能体", count: 2 }],
};

const graphPathsFixture: GraphPathView = {
  graph_version: "lib-books-v2-20260828",
  source_id: "topic:ai",
  target_id: "book:1",
  truncated: false,
  paths: [
    { path_id: "graphpath:v2:dG9waWM6YWk.Ym9vazox.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", node_ids: ["topic:ai", "book:1"], edge_ids: ["edge:1"], hop_count: 1, score: 1, evidence_refs: ["graph:v2"] },
    { path_id: "graphpath:v2:dG9waWM6YWk.Ym9vazox.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", node_ids: ["topic:ai", "work:1", "book:1"], edge_ids: ["edge:2", "edge:3"], hop_count: 2, score: 0.85, evidence_refs: ["graph:v2"] },
  ],
  graph: {
    graph_version: "lib-books-v2-20260828",
    query: "topic:ai->book:1",
    truncated: false,
    nodes: [
      { id: "topic:ai", type: "Topic", label: "人工智能", properties: {} },
      { id: "book:1", type: "Book", label: "智能系统", properties: {} },
    ],
    edges: [{ id: "edge:1", source: "topic:ai", target: "book:1", type: "IN_TOPIC", label: "IN_TOPIC" }],
  },
};

describe("library read resilience", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
    vi.mocked(explorationClient.overview).mockReset();
    vi.mocked(explorationClient.graphSearch).mockReset();
    vi.mocked(explorationClient.graphPaths).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries a transient overview response once and keeps the real result", async () => {
    vi.mocked(explorationClient.overview)
      .mockRejectedValueOnce(new Error("EXPLORE_HTTP_503"))
      .mockResolvedValueOnce(overviewFixture);
    const library = useLibraryStore();

    const pending = library.loadOverview();
    await vi.advanceTimersByTimeAsync(350);
    await pending;

    expect(explorationClient.overview).toHaveBeenCalledTimes(2);
    expect(library.overview?.dataset_version).toBe("books-test");
    expect(library.overviewError).toBe("");
  });

  it("does not retry a contract violation and exposes a bounded error", async () => {
    vi.mocked(explorationClient.overview).mockRejectedValue(new Error("INVALID_EXPLORATION_RESPONSE"));
    const library = useLibraryStore();

    await library.loadOverview();

    expect(explorationClient.overview).toHaveBeenCalledTimes(1);
    expect(library.overview).toBeNull();
    expect(library.overviewError).toBe("馆藏数据暂时无法读取。");
  });

  it("keeps overview and graph failures independently visible", async () => {
    vi.mocked(explorationClient.overview).mockResolvedValue(overviewFixture);
    vi.mocked(explorationClient.graphSearch).mockRejectedValue(new Error("EXPLORE_HTTP_503"));
    const library = useLibraryStore();

    await library.loadOverview();
    const graphPending = library.searchGraph("人工智能");
    await vi.advanceTimersByTimeAsync(350);
    await graphPending;

    expect(library.overviewError).toBe("");
    expect(library.graphError).toContain("EXPLORE_HTTP_503");
    expect(library.error).toContain("EXPLORE_HTTP_503");
  });

  it("highlights the exact recommendation path and reports a bounded mismatch", async () => {
    vi.mocked(explorationClient.graphPaths).mockResolvedValue(graphPathsFixture);
    const library = useLibraryStore();
    const expected = graphPathsFixture.paths[1].path_id;

    await library.loadGraphPaths("topic:ai", "book:1", expected);
    expect(library.highlightedPathId).toBe(expected);
    expect(library.graphPathError).toBe("");

    await library.loadGraphPaths("topic:ai", "book:1", "graphpath:v2:dG9waWM6YWk.Ym9vazox.cccccccccccccccccccccccccccccccc");
    expect(library.highlightedPathId).toBe(graphPathsFixture.paths[0].path_id);
    expect(library.graphPathError).toContain("未返回推荐时引用的精确路径");
  });
});
