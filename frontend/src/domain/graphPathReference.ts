export interface GraphPathRoute {
  sourceId: string;
  targetId: string;
}

const routePattern = /^graphpath:v2:([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\.[0-9a-f]{32}$/;

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  const binary = window.atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

export function parseGraphPathRoute(reference: string): GraphPathRoute | null {
  const match = routePattern.exec(reference);
  if (!match) return null;
  try {
    const sourceId = decodeBase64Url(match[1]);
    const targetId = decodeBase64Url(match[2]);
    if (!sourceId || !targetId || sourceId === targetId || sourceId.length > 256 || targetId.length > 256) return null;
    return { sourceId, targetId };
  } catch {
    return null;
  }
}
