import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useInteractionStore } from "./interaction";
import { useSessionStore } from "./session";

describe("interaction store guest boundary", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.stubGlobal("fetch", vi.fn());
  });

  it("keeps guest feedback inside the browser session and never sends a POST", async () => {
    const session = useSessionStore();
    const interaction = useInteractionStore();
    session.setMode("guest");

    await interaction.submit(undefined, "FAVORITE");

    expect(fetch).not.toHaveBeenCalled();
    expect(interaction.localFeedback).toEqual(["已喜欢"]);
    session.reset();
    expect(interaction.localFeedback).toEqual([]);
  });
});
