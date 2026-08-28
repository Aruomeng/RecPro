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

  it("accepts only bounded graph path evidence", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      graph_version: "lib-books-v2-20260828", source_id: "book:1", target_id: "topic:1", truncated: false,
      paths: [{ path_id: "graphpath:abc", node_ids: ["book:1", "work:1", "topic:1"], edge_ids: ["edge:1", "edge:2"], hop_count: 2, score: 0.85, evidence_refs: ["graphpath:abc"] }],
      graph: {
        graph_version: "lib-books-v2-20260828", query: "book:1->topic:1", truncated: false,
        nodes: [{ id: "book:1", type: "Book", label: "Agent", properties: {} }, { id: "work:1", type: "Work", label: "Agent Work", properties: {} }, { id: "topic:1", type: "Topic", label: "AI", properties: {} }],
        edges: [{ id: "edge:1", source: "book:1", target: "work:1", type: "INSTANCE_OF", label: "INSTANCE_OF" }, { id: "edge:2", source: "work:1", target: "topic:1", type: "HAS_TOPIC", label: "HAS_TOPIC" }],
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    const result = await explorationClient.graphPaths("book:1", "topic:1");
    expect(result.paths[0].hop_count).toBe(2);
  });

  it("rejects a graph path whose node count disagrees with hop count", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      graph_version: "v2", source_id: "book:1", target_id: "topic:1", truncated: false,
      paths: [{ path_id: "graphpath:abc", node_ids: ["book:1", "topic:1"], edge_ids: ["e1", "e2"], hop_count: 2, score: 0.85, evidence_refs: ["graphpath:abc"] }],
      graph: { graph_version: "v2", query: "q", truncated: false, nodes: [], edges: [] },
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(explorationClient.graphPaths("book:1", "topic:1")).rejects.toThrow("INVALID_EXPLORATION_RESPONSE");
  });
});
