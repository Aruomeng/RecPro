import { describe, expect, it } from "vitest";

import { identityHeaders } from "./authHeaders";

describe("identityHeaders", () => {
  it("does not invent an identity for guest read requests", () => {
    expect(identityHeaders({ mode: "guest" })).toEqual({});
  });

  it("uses bearer authentication for a signed-in reader", () => {
    expect(identityHeaders({ mode: "authenticated", accessToken: "jwt-value" })).toEqual({
      Authorization: "Bearer jwt-value",
    });
  });

  it("keeps the research demo header behind an explicit demo identity", () => {
    expect(identityHeaders({ mode: "demo", demoUserId: 1001 })).toEqual({ "X-Demo-User-Id": "1001" });
    expect(() => identityHeaders({ mode: "authenticated" })).toThrow("AUTH_ACCESS_TOKEN_REQUIRED");
  });
});
