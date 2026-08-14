export interface CountBucket { name: string; count: number }
export interface LibraryOverview {
  schema_version: string;
  dataset_version: string;
  graph_version: string;
  generated_at: string;
  totals: { resources: number; books: number; papers: number; tags: number };
  graph: { nodes: number; relationships: number };
  availability: CountBucket[];
  categories: CountBucket[];
  publication_decades: Array<{ year: number; count: number }>;
  popular_topics: CountBucket[];
}

export interface ResourceDetail {
  resource_id: number;
  resource_type: string;
  external_id: string;
  title: string;
  authors: string[];
  abstract?: string;
  keywords: string[];
  category_code?: string;
  publication_year?: number;
  publisher?: string;
  language?: string;
  difficulty_level?: number;
  availability_status: string;
  isbn?: string;
  call_number?: string;
  location?: string;
  borrowable_copies: number;
  tags: string[];
}

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  subtitle?: string;
  resource_id?: number;
  properties: Record<string, string | number | boolean>;
}
export interface GraphEdge { id: string; source: string; target: string; type: string; label: string }
export interface GraphView { graph_version: string; query: string; nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean }
