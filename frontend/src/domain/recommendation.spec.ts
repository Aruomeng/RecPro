import { describe, expect, it } from "vitest";

import { isUuid } from "./recommendation";

describe("recommendation identity", () => {
  it("accepts deterministic UUIDv5 identities used by approved replay plans", () => {
    expect(isUuid("f343aa37-5020-5276-aa90-0decd9692c91")).toBe(true);
    expect(isUuid("55848636-0fd0-5621-a5b4-6d4821a26b65")).toBe(true);
  });

  it("still accepts browser-generated UUIDv4 identities and rejects malformed values", () => {
    expect(isUuid("773bcfaa-5faf-4b17-95ae-44c4f747d60c")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
  });
});
