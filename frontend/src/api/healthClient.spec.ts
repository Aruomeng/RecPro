import { describe, expect, it, vi } from "vitest";

import { createHealthClient, HealthApiError } from "./healthClient";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("healthClient", () => {
  it("reads the liveness contract from the versioned path", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      status: "UP",
      service: "recpro-backend",
      version: "0.1.0",
      time: "2026-08-02T10:30:00.000Z",
    }));
    const client = createHealthClient({ baseUrl: "http://backend:8000/", fetcher });

    await expect(client.getLiveness()).resolves.toMatchObject({ status: "UP" });
    expect(fetcher).toHaveBeenCalledWith(
      "http://backend:8000/api/v1/health/live",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });

  it("accepts truthful degraded readiness with recommendation disabled", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      status: "DEGRADED",
      can_recommend: false,
      components: {
        mysql: { status: "UP", required: true },
        recommendation_pipeline: { status: "DISABLED", required: false },
      },
      config_bundle_version: "g1-skeleton-v1",
      checked_at: "2026-08-02T10:30:00.000Z",
    }));
    const client = createHealthClient({ fetcher });

    await expect(client.getReadiness()).resolves.toMatchObject({
      status: "DEGRADED",
      can_recommend: false,
    });
  });

  it("preserves the stable error code from a 503 error contract", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      error: {
        code: "UNSAFE_DATABASE_PRIVILEGES",
        message: "localized text is not a client contract",
        details: {},
        retryable: false,
      },
      request_id: "846b1454-54a0-4e2b-a744-c10e840a1c73",
      trace_id: "80e67683-4544-4ae7-b347-f8ffefc06054",
    }, 503));
    const client = createHealthClient({ fetcher });

    const error = await client.getReadiness().catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(HealthApiError);
    expect(error).toMatchObject({
      status: 503,
      code: "UNSAFE_DATABASE_PRIVILEGES",
      retryable: false,
    });
  });

  it("fails with a stable timeout instead of leaving health pending forever", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        })
      ));
      const client = createHealthClient({ fetcher, timeoutMs: 25 });
      const assertion = expect(client.getLiveness()).rejects.toMatchObject({
        status: 0,
        code: "HEALTH_REQUEST_TIMEOUT",
        retryable: true,
      });

      await vi.advanceTimersByTimeAsync(26);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it("propagates caller cancellation without mislabeling it as a timeout", async () => {
    const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("superseded", "AbortError")),
          { once: true },
        );
      })
    ));
    const caller = new AbortController();
    const client = createHealthClient({ fetcher, timeoutMs: 5_000 });
    const request = client.getReadiness({ signal: caller.signal });

    caller.abort("superseded");

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("rejects a success payload that violates the frozen schema", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      status: "UP",
      service: "another-service",
      version: "0.1.0",
      time: "2026-08-02T10:30:00.000Z",
    }));
    const client = createHealthClient({ fetcher });

    await expect(client.getLiveness()).rejects.toMatchObject({
      code: "INVALID_HEALTH_RESPONSE",
    });
  });

  it.each([
    {
      status: "NOT_READY",
      can_recommend: true,
      components: { mysql: { status: "UP", required: true } },
    },
    {
      status: "READY",
      can_recommend: true,
      components: {
        mysql: { status: "UP", required: true },
        recommendation_pipeline: { status: "UP", required: true },
      },
    },
  ])("rejects any premature G1 recommendation claim: %o", async (contradiction) => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({
      ...contradiction,
      config_bundle_version: "rec-1.0.0",
      checked_at: "2026-08-02T10:30:00.000Z",
    }));
    const client = createHealthClient({ fetcher });

    await expect(client.getReadiness()).rejects.toMatchObject({
      code: "INVALID_HEALTH_RESPONSE",
    });
  });
});
