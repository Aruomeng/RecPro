import { constants } from "node:fs";
import { access, lstat, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const RUN_ID_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;

export class SafeBuildError extends Error {
  constructor(code, message, options) {
    super(message, options);
    this.name = "SafeBuildError";
    this.code = code;
  }
}

export function parseBuildRunId(value) {
  if (typeof value !== "string" || !RUN_ID_PATTERN.test(value)) {
    throw new SafeBuildError(
      "INVALID_BUILD_RUN_ID",
      "RECPRO_BUILD_RUN_ID must contain 1-64 lowercase ASCII letters, digits, or internal hyphens.",
    );
  }
  return value;
}

export function createBuildPlan({ projectRoot, runId }) {
  if (typeof projectRoot !== "string" || projectRoot.length === 0) {
    throw new SafeBuildError("INVALID_PROJECT_ROOT", "A non-empty project root is required.");
  }

  const normalizedRunId = parseBuildRunId(runId);
  const normalizedProjectRoot = resolve(projectRoot);
  const distRoot = resolve(normalizedProjectRoot, "dist");
  const outDir = resolve(distRoot, normalizedRunId);

  if (dirname(outDir) !== distRoot) {
    throw new SafeBuildError("BUILD_TARGET_OUTSIDE_DIST", "The build target must be a direct child of dist.");
  }

  return Object.freeze({
    projectRoot: normalizedProjectRoot,
    runId: normalizedRunId,
    distRoot,
    outDir,
  });
}

async function pathState(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error && typeof error === "object" && error.code === "ENOENT") return undefined;
    throw error;
  }
}

async function ensurePlainDistDirectory(distRoot) {
  let state = await pathState(distRoot);
  if (!state) {
    try {
      await mkdir(distRoot, { recursive: false, mode: 0o755 });
    } catch (error) {
      if (!error || typeof error !== "object" || error.code !== "EEXIST") throw error;
    }
    state = await pathState(distRoot);
  }

  if (!state?.isDirectory() || state.isSymbolicLink()) {
    throw new SafeBuildError(
      "UNSAFE_DIST_ROOT",
      "The dist root must be a real directory inside the frontend project.",
    );
  }
}

export async function reserveBuildTarget(plan) {
  await ensurePlainDistDirectory(plan.distRoot);

  try {
    await access(plan.outDir, constants.F_OK);
    throw new SafeBuildError(
      "BUILD_TARGET_EXISTS",
      `Build target already exists for run ${plan.runId}; choose a new RECPRO_BUILD_RUN_ID.`,
    );
  } catch (error) {
    if (error instanceof SafeBuildError) throw error;
    if (!error || typeof error !== "object" || error.code !== "ENOENT") throw error;
  }

  try {
    await mkdir(plan.outDir, { recursive: false, mode: 0o755 });
  } catch (error) {
    if (error && typeof error === "object" && error.code === "EEXIST") {
      throw new SafeBuildError(
        "BUILD_TARGET_EXISTS",
        `Build target was claimed concurrently for run ${plan.runId}; choose a new RECPRO_BUILD_RUN_ID.`,
        { cause: error },
      );
    }
    throw error;
  }
}

export function isMainModule(metaUrl, argvEntry) {
  return typeof argvEntry === "string" && pathToFileURL(resolve(argvEntry)).href === metaUrl;
}

export async function runSafeBuild({ projectRoot = process.cwd(), runId = process.env.RECPRO_BUILD_RUN_ID } = {}) {
  const plan = createBuildPlan({ projectRoot, runId });
  await reserveBuildTarget(plan);

  const { build } = await import("vite");
  await build({
    root: plan.projectRoot,
    build: {
      outDir: plan.outDir,
      emptyOutDir: false,
    },
  });

  return plan;
}

if (isMainModule(import.meta.url, process.argv[1])) {
  runSafeBuild().catch((error) => {
    const code = error instanceof SafeBuildError ? error.code : "BUILD_FAILED";
    process.stderr.write(`[${code}] ${error instanceof Error ? error.message : "Unknown build failure."}\n`);
    process.exitCode = 1;
  });
}
