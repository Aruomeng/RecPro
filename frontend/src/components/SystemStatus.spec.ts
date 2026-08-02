import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { HealthApiError } from "../api/healthClient";
import SystemStatus from "./SystemStatus.vue";

const live = {
  phase: "success" as const,
  value: {
    status: "UP" as const,
    service: "recpro-backend" as const,
    version: "0.1.0",
    time: "2026-08-02T10:30:00.000Z",
  },
};

describe("SystemStatus", () => {
  it("separates process liveness from an intentionally disabled recommendation pipeline", () => {
    const wrapper = mount(SystemStatus, {
      props: {
        liveness: live,
        readiness: {
          phase: "success",
          value: {
            status: "DEGRADED",
            can_recommend: false,
            components: {
              mysql: { status: "UP", required: true },
              recommendation_pipeline: { status: "DISABLED", required: false },
            },
            config_bundle_version: "g1-skeleton-v1",
            checked_at: "2026-08-02T10:30:00.000Z",
          },
        },
      },
    });

    expect(wrapper.text()).toContain("进程存活");
    expect(wrapper.text()).toContain("推荐能力尚未启用");
    expect(wrapper.text()).toContain("不会生成推荐结果");
    expect(wrapper.text()).toContain("MySQL 核心存储");
  });

  it("explains a database privilege safety failure by stable error code", () => {
    const wrapper = mount(SystemStatus, {
      props: {
        liveness: live,
        readiness: {
          phase: "error",
          error: new HealthApiError({
            status: 503,
            code: "UNSAFE_DATABASE_PRIVILEGES",
            message: "server-localized message",
            traceId: "80e67683-4544-4ae7-b347-f8ffefc06054",
          }),
        },
      },
    });

    expect(wrapper.text()).toContain("安全检查未通过");
    expect(wrapper.text()).toContain("数据库账号权限超出安全范围");
    expect(wrapper.text()).toContain("80e67683-4544-4ae7-b347-f8ffefc06054");
    expect(wrapper.text()).not.toContain("server-localized message");
  });

  it("labels a core storage 503 as dependency not ready", () => {
    const wrapper = mount(SystemStatus, {
      props: {
        liveness: live,
        readiness: {
          phase: "error",
          error: new HealthApiError({
            status: 503,
            code: "CORE_STORAGE_UNAVAILABLE",
            message: "message can be localized",
            retryable: true,
          }),
        },
      },
    });

    expect(wrapper.text()).toContain("依赖未就绪");
    expect(wrapper.text()).toContain("核心存储当前不可用");
    expect(wrapper.text()).toContain("进程存活");
  });
});
