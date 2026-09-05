import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { explorationClient } from "../api/explorationClient";
import type { LibraryOverview } from "../domain/exploration";
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

describe("library read resilience", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
    vi.mocked(explorationClient.overview).mockReset();
    vi.mocked(explorationClient.graphSearch).mockReset();
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
});
