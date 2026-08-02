import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { createBuildPlan } from "./safe-build.mjs";
import { validatePreviewTarget } from "./safe-preview.mjs";

async function createPlainPreviewFixture(prefix) {
  const projectRoot = await mkdtemp(join(tmpdir(), prefix));
  const plan = createBuildPlan({ projectRoot, runId: "preview-run" });
  await mkdir(plan.outDir, { recursive: true });
  await writeFile(join(plan.outDir, "index.html"), "<!doctype html>\n", {
    encoding: "utf8",
    flag: "wx",
  });
  return plan;
}

describe("validatePreviewTarget", () => {
  it("accepts a plain append-only build directory with a plain index", async () => {
    const plan = await createPlainPreviewFixture("recpro-safe-preview-ok-");

    await expect(validatePreviewTarget(plan)).resolves.toBeUndefined();
  });

  it("rejects a symbolic-link dist root", async () => {
    const projectRoot = await mkdtemp(join(tmpdir(), "recpro-safe-preview-link-"));
    const externalRoot = await mkdtemp(join(tmpdir(), "recpro-safe-preview-external-"));
    await mkdir(join(externalRoot, "preview-run"));
    await writeFile(join(externalRoot, "preview-run", "index.html"), "safe fixture\n", {
      encoding: "utf8",
      flag: "wx",
    });
    await symlink(externalRoot, join(projectRoot, "dist"), "dir");
    const plan = createBuildPlan({ projectRoot, runId: "preview-run" });

    await expect(validatePreviewTarget(plan)).rejects.toMatchObject({
      code: "UNSAFE_PREVIEW_DIST_ROOT",
    });
  });

  it("rejects a missing or symbolic-link index", async () => {
    const projectRoot = await mkdtemp(join(tmpdir(), "recpro-safe-preview-index-"));
    const plan = createBuildPlan({ projectRoot, runId: "preview-run" });
    await mkdir(plan.outDir, { recursive: true });

    await expect(validatePreviewTarget(plan)).rejects.toMatchObject({
      code: "PREVIEW_INDEX_MISSING",
    });

    const externalIndex = join(projectRoot, "external-index.html");
    await writeFile(externalIndex, "safe fixture\n", { encoding: "utf8", flag: "wx" });
    await symlink(externalIndex, join(plan.outDir, "index.html"));
    await expect(validatePreviewTarget(plan)).rejects.toMatchObject({
      code: "PREVIEW_INDEX_MISSING",
    });
  });
});
