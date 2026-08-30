import { describe, expect, it, vi } from "vitest";

import { createRuntimeDiagnosticsClient, RuntimeDiagnosticsApiError } from "./runtimeDiagnosticsClient";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const validPayload = {
  schema_version: "runtime-diagnostics-v1",
  registry_closed: false,
  resource_count: 1,
  resources: [{
    resource_type: "MySQLConnectionPool",
    metrics: { pool_size: 4, free_size: 3, average_acquire_ms: 2.5 },
  }],
  collected_at: "2026-08-30T05:00:00.000Z",
};

describe("runtimeDiagnosticsClient", () => {
  it("reads the opt-in diagnostics path with the formal bearer token", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(validPayload));
    const client = createRuntimeDiagnosticsClient({ fetcher });

    await expect(client.get("research-token")).resolves.toMatchObject({
      schema_version: "runtime-diagnostics-v1",
      resource_count: 1,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/debug/runtime",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        headers: { Accept: "application/json", Authorization: "Bearer research-token" },
      }),
    );
  });

  it("rejects a response that contains an unbounded metric key", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      ...validPayload,
      resources: [{
        ...validPayload.resources[0],
        metrics: { ...validPayload.resources[0].metrics, password: "secret" },
      }],
    }));
    const client = createRuntimeDiagnosticsClient({ fetcher });

    await expect(client.get("research-token")).rejects.toMatchObject({
      code: "INVALID_RUNTIME_DIAGNOSTICS_RESPONSE",
    });
  });

  it("preserves the sanitized server error contract", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      error: { code: "RESOURCE_ACCESS_FORBIDDEN", message: "研究管理员身份 required", details: {}, retryable: false },
      request_id: "846b1454-54a0-4e2b-a744-c10e840a1c73",
      trace_id: "80e67683-4544-4ae7-b347-f8ffefc06054",
    }, 403));
    const client = createRuntimeDiagnosticsClient({ fetcher });

    const error = await client.get("research-token").catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(RuntimeDiagnosticsApiError);
    expect(error).toMatchObject({ status: 403, code: "RESOURCE_ACCESS_FORBIDDEN", retryable: false });
  });
});
