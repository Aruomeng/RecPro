import { lstat } from "node:fs/promises";
import { resolve } from "node:path";

import { createBuildPlan, isMainModule, SafeBuildError } from "./safe-build.mjs";

async function requirePlainFile(path, code) {
  let state;
  try {
    state = await lstat(path);
  } catch (error) {
    if (error && typeof error === "object" && error.code === "ENOENT") {
      throw new SafeBuildError(code, `Preview input is missing: ${path}`);
    }
    throw error;
  }
  if (!state.isFile() || state.isSymbolicLink()) {
    throw new SafeBuildError(code, `Preview input must be a plain file: ${path}`);
  }
}

export async function validatePreviewTarget(plan) {
  const distState = await lstat(plan.distRoot).catch((error) => {
    if (error && typeof error === "object" && error.code === "ENOENT") {
      throw new SafeBuildError("PREVIEW_DIST_MISSING", "The dist root does not exist.");
    }
    throw error;
  });
  if (!distState.isDirectory() || distState.isSymbolicLink()) {
    throw new SafeBuildError(
      "UNSAFE_PREVIEW_DIST_ROOT",
      "The dist root must be a real directory inside the frontend project.",
    );
  }

  const state = await lstat(plan.outDir).catch((error) => {
    if (error && typeof error === "object" && error.code === "ENOENT") {
      throw new SafeBuildError("PREVIEW_TARGET_MISSING", "The selected build run does not exist.");
    }
    throw error;
  });
  if (!state.isDirectory() || state.isSymbolicLink()) {
    throw new SafeBuildError(
      "UNSAFE_PREVIEW_TARGET",
      "The selected build run must be a real directory.",
    );
  }
  await requirePlainFile(resolve(plan.outDir, "index.html"), "PREVIEW_INDEX_MISSING");
}

export async function runSafePreview({
  projectRoot = process.cwd(),
  runId = process.env.RECPRO_BUILD_RUN_ID,
} = {}) {
  const plan = createBuildPlan({ projectRoot, runId });
  await validatePreviewTarget(plan);
  const { preview } = await import("vite");
  return preview({
    root: plan.projectRoot,
    build: { outDir: plan.outDir },
    preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  });
}

if (isMainModule(import.meta.url, process.argv[1])) {
  runSafePreview().catch((error) => {
    const code = error instanceof SafeBuildError ? error.code : "PREVIEW_FAILED";
    process.stderr.write(`[${code}] ${error instanceof Error ? error.message : "Unknown preview failure."}\n`);
    process.exitCode = 1;
  });
}
