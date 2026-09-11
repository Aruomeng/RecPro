import { describe, expect, it } from "vitest";

import { parseGraphPathRoute } from "./graphPathReference";

function encode(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

describe("graph path reference", () => {
  it("recovers the bounded public endpoints from a v2 evidence reference", () => {
    const reference = `graphpath:v2:${encode("topic:多智能体")}.${encode("book:one")}.${"a".repeat(32)}`;
    expect(parseGraphPathRoute(reference)).toEqual({
      sourceId: "topic:多智能体",
      targetId: "book:one",
    });
  });

  it("does not treat legacy, malformed, or same-endpoint references as routeable", () => {
    expect(parseGraphPathRoute(`graphpath:${"a".repeat(32)}`)).toBeNull();
    expect(parseGraphPathRoute("graphpath:v2:not-valid")).toBeNull();
    const endpoint = encode("book:one");
    expect(parseGraphPathRoute(`graphpath:v2:${endpoint}.${endpoint}.${"a".repeat(32)}`)).toBeNull();
  });
});
