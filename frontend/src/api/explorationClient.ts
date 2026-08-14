import type { GraphView, LibraryOverview, ResourceDetail } from "../domain/exploration";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function text(value: unknown): value is string { return typeof value === "string"; }
function count(value: unknown): value is number { return typeof value === "number" && Number.isInteger(value) && value >= 0; }
function buckets(value: unknown): boolean { return Array.isArray(value) && value.every((item) => record(item) && text(item.name) && count(item.count)); }
function validOverview(value: unknown): value is LibraryOverview {
  if (!record(value) || !record(value.totals) || !record(value.graph)) return false;
  return text(value.schema_version) && text(value.dataset_version) && text(value.graph_version) && text(value.generated_at) &&
    count(value.totals.resources) && count(value.totals.books) && count(value.totals.papers) && count(value.totals.tags) &&
    count(value.graph.nodes) && count(value.graph.relationships) && buckets(value.availability) && buckets(value.categories) &&
    buckets(value.popular_topics) && Array.isArray(value.publication_decades) && value.publication_decades.every((item) => record(item) && count(item.year) && count(item.count));
}
function validResource(value: unknown): value is ResourceDetail {
  return record(value) && count(value.resource_id) && value.resource_id > 0 && text(value.resource_type) && text(value.external_id) && text(value.title) &&
    Array.isArray(value.authors) && value.authors.every(text) && Array.isArray(value.keywords) && value.keywords.every(text) &&
    text(value.availability_status) && count(value.borrowable_copies) && Array.isArray(value.tags) && value.tags.every(text);
}
function validGraph(value: unknown): value is GraphView {
  if (!record(value) || !text(value.graph_version) || !text(value.query) || typeof value.truncated !== "boolean" || !Array.isArray(value.nodes) || !Array.isArray(value.edges)) return false;
  return value.nodes.length <= 60 && value.edges.length <= 120 && value.nodes.every((node) => record(node) && text(node.id) && text(node.type) && text(node.label) && record(node.properties)) &&
    value.edges.every((edge) => record(edge) && text(edge.id) && text(edge.source) && text(edge.target) && text(edge.type) && text(edge.label));
}

async function getJson<T>(path: string, validate: (value: unknown) => value is T, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { headers: { Accept: "application/json" }, cache: "no-store", signal });
  if (!response.ok) throw new Error(`EXPLORE_HTTP_${response.status}`);
  const payload: unknown = await response.json();
  if (!validate(payload)) throw new Error("INVALID_EXPLORATION_RESPONSE");
  return payload;
}

export const explorationClient = {
  overview: (signal?: AbortSignal) => getJson("/api/v1/explore/overview", validOverview, signal),
  resource: (id: number, signal?: AbortSignal) => getJson(`/api/v1/explore/resources/${encodeURIComponent(String(id))}`, validResource, signal),
  graphSearch: (query: string, limit = 30, signal?: AbortSignal) => getJson(`/api/v1/explore/graph/search?q=${encodeURIComponent(query)}&limit=${limit}`, validGraph, signal),
  graphNeighbors: (entityId: string, limit = 40, signal?: AbortSignal) => getJson(`/api/v1/explore/graph/nodes/${encodeURIComponent(entityId)}/neighbors?limit=${limit}`, validGraph, signal),
};
