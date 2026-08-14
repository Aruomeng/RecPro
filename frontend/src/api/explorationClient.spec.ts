import { afterEach, describe, expect, it, vi } from "vitest";
import { explorationClient } from "./explorationClient";

afterEach(() => vi.unstubAllGlobals());

describe("exploration client", () => {
  it("accepts a bounded public graph", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      graph_version: "lib-books-v1-20260810", query: "agent", truncated: false,
      nodes: [{ id: "book:1", type: "Book", label: "Agent", properties: {}, resource_id: 1 }],
      edges: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    const graph = await explorationClient.graphSearch("agent");
    expect(graph.nodes[0].resource_id).toBe(1);
  });

  it("rejects an oversized or malformed graph response", async () => {
    const nodes = Array.from({ length: 61 }, (_, index) => ({ id: String(index), type: "Book", label: "x", properties: {} }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      graph_version: "v", query: "x", truncated: true, nodes, edges: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(explorationClient.graphSearch("x")).rejects.toThrow("INVALID_EXPLORATION_RESPONSE");
  });
});
