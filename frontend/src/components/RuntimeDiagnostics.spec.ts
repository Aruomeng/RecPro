import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import RuntimeDiagnostics from "./RuntimeDiagnostics.vue";

describe("RuntimeDiagnostics", () => {
  it("renders only the public metric projection and emits an explicit refresh", async () => {
    const wrapper = mount(RuntimeDiagnostics, {
      props: {
        runtime: {
          phase: "success",
          value: {
            schema_version: "runtime-diagnostics-v1",
            registry_closed: false,
            resource_count: 1,
            resources: [{
              resource_type: "MySQLConnectionPool",
              metrics: { pool_size: 4, free_size: 3, average_acquire_ms: 2.5 },
            }],
            collected_at: "2026-08-30T05:00:00.000Z",
          },
        },
      },
    });

    expect(wrapper.text()).toContain("MySQLConnectionPool");
    expect(wrapper.text()).toContain("平均获取耗时");
    expect(wrapper.text()).toContain("2.5 毫秒");
    expect(wrapper.text()).not.toContain("password");

    await wrapper.get(".runtime-diagnostics__refresh").trigger("click");
    expect(wrapper.emitted("refresh")).toHaveLength(1);
  });

  it("does not pretend that an unauthorized visitor has diagnostics", () => {
    const wrapper = mount(RuntimeDiagnostics, { props: { runtime: { phase: "idle" } } });
    expect(wrapper.text()).toContain("诊断未启用");
    expect(wrapper.text()).toContain("研究管理员正式登录");
  });

  it("shows a safe error code and retry action", async () => {
    const wrapper = mount(RuntimeDiagnostics, {
      props: { runtime: { phase: "error", error: { code: "CORE_STORAGE_UNAVAILABLE" } } },
    });

    expect(wrapper.text()).toContain("CORE_STORAGE_UNAVAILABLE");
    await wrapper.get(".runtime-diagnostics__state--error .state-action").trigger("click");
    expect(wrapper.emitted("refresh")).toHaveLength(1);
  });
});
