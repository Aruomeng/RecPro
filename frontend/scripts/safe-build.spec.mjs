import { mkdtemp, mkdir, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  createBuildPlan,
  parseBuildRunId,
  reserveBuildTarget,
  SafeBuildError,
} from "./safe-build.mjs";

describe("parseBuildRunId", () => {
  it.each([
    "a",
    "container-image",
    "g1-20260802t101500",
    "a12345678901234567890123456789012345678901234567890123456789012z",
  ])("accepts an append-only run id: %s", (runId) => {
    expect(parseBuildRunId(runId)).toBe(runId);
  });

  it.each([
    undefined,
    "",
    "UPPERCASE",
    "has_underscore",
    "has.dot",
    "-leading",
    "trailing-",
    "../escape",
    "two words",
    "a123456789012345678901234567890123456789012345678901234567890123z",
  ])("rejects an unsafe or ambiguous run id: %s", (runId) => {
    expect(() => parseBuildRunId(runId)).toThrowError(
      expect.objectContaining({ code: "INVALID_BUILD_RUN_ID" }),
    );
  });
});

describe("createBuildPlan", () => {
  it("resolves the target as one direct child below the project dist directory", () => {
    const projectRoot = resolve("/tmp", "recpro-frontend-fixture");

    expect(createBuildPlan({ projectRoot, runId: "ci-20260802-001" })).toEqual({
      projectRoot,
      runId: "ci-20260802-001",
      distRoot: resolve(projectRoot, "dist"),
      outDir: resolve(projectRoot, "dist", "ci-20260802-001"),
    });
  });

  it("fails with a stable code when the project root is missing", () => {
    expect(() => createBuildPlan({ projectRoot: "", runId: "valid-run" })).toThrow(
      expect.objectContaining({
        name: SafeBuildError.name,
        code: "INVALID_PROJECT_ROOT",
      }),
    );
  });
});

describe("reserveBuildTarget", () => {
  it("claims a new append-only run exactly once", async () => {
    const projectRoot = await mkdtemp(join(tmpdir(), "recpro-safe-build-once-"));
    const plan = createBuildPlan({ projectRoot, runId: "test-once" });

    await expect(reserveBuildTarget(plan)).resolves.toBeUndefined();
    await expect(reserveBuildTarget(plan)).rejects.toMatchObject({
      code: "BUILD_TARGET_EXISTS",
    });
  });

  it("rejects a symbolic-link dist root", async () => {
    const projectRoot = await mkdtemp(join(tmpdir(), "recpro-safe-build-link-"));
    const externalRoot = await mkdtemp(join(tmpdir(), "recpro-safe-build-external-"));
    await symlink(externalRoot, join(projectRoot, "dist"), "dir");
    const plan = createBuildPlan({ projectRoot, runId: "test-link" });

    await expect(reserveBuildTarget(plan)).rejects.toMatchObject({
      code: "UNSAFE_DIST_ROOT",
    });
  });

  it("allows only one concurrent claimant and preserves the claimed directory", async () => {
    const projectRoot = await mkdtemp(join(tmpdir(), "recpro-safe-build-race-"));
    await mkdir(join(projectRoot, "dist"));
    const plan = createBuildPlan({ projectRoot, runId: "test-race" });

    const results = await Promise.allSettled([
      reserveBuildTarget(plan),
      reserveBuildTarget(plan),
    ]);

    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    const rejected = results.find((result) => result.status === "rejected");
    expect(rejected).toMatchObject({
      reason: expect.objectContaining({ code: "BUILD_TARGET_EXISTS" }),
    });
  });
});
