import type { ComponentReadiness, ReadinessResponse } from "../domain/health";
import { isHealthFailure, isRecommendationPipelineDisabled } from "../domain/health";

export type Tone = "positive" | "warning" | "negative" | "neutral";

export interface StatusCopy {
  label: string;
  detail: string;
  tone: Tone;
}

export const componentNames: Record<string, string> = {
  config_bundle: "配置包",
  mysql: "MySQL 核心存储",
  chroma: "Chroma 向量检索",
  neo4j: "Neo4j 知识图谱",
  llm: "LLM 提供方",
  recommendation_pipeline: "推荐链路",
};

export const componentStatusNames: Record<ComponentReadiness["status"], string> = {
  UP: "正常",
  DOWN: "不可用",
  DISABLED: "未启用",
  MOCK: "模拟实现",
  UNKNOWN: "未知",
};

const readinessErrorCopies: Record<string, StatusCopy> = {
  CORE_STORAGE_UNAVAILABLE: {
    label: "依赖未就绪",
    detail: "核心存储当前不可用，系统不会承接推荐请求。",
    tone: "negative",
  },
  UNSAFE_DATABASE_PRIVILEGES: {
    label: "安全检查未通过",
    detail: "数据库账号权限超出安全范围，系统已拒绝进入就绪状态。",
    tone: "negative",
  },
  CONFIG_BUNDLE_INVALID: {
    label: "配置未就绪",
    detail: "配置包无效或校验失败，推荐能力保持关闭。",
    tone: "negative",
  },
  HEALTH_REQUEST_TIMEOUT: {
    label: "健康检查超时",
    detail: "健康接口未在时限内响应，请检查服务负载或网络状态。",
    tone: "negative",
  },
};

export function presentReadiness(readiness: ReadinessResponse): StatusCopy {
  if (isRecommendationPipelineDisabled(readiness)) {
    return {
      label: "推荐能力尚未启用",
      detail: "基础服务可观测，但 G1 尚未实现推荐链路，不会生成推荐结果。",
      tone: "warning",
    };
  }
  return {
    label: "推荐能力不可用",
    detail: "当前组件状态不足以安全执行推荐，请检查下方依赖状态。",
    tone: "negative",
  };
}

export function presentReadinessError(error: unknown): StatusCopy {
  if (isHealthFailure(error) && readinessErrorCopies[error.code]) {
    return readinessErrorCopies[error.code];
  }
  return {
    label: "无法读取就绪状态",
    detail: "无法连接健康接口或响应不符合契约，请检查后端与网络。",
    tone: "negative",
  };
}

export function componentTone(component: ComponentReadiness): Tone {
  if (component.status === "UP") return "positive";
  if (component.status === "DOWN" && component.required) return "negative";
  if (component.status === "DOWN" || component.status === "DISABLED") return "warning";
  return "neutral";
}
