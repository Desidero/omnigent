import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  AUTO_HARNESS_LABEL_KEY,
  isCostRoutingSession,
  isSubagentRoutingSession,
  shortModelName,
  SUBAGENT_ROUTING_LABEL_KEY,
  subagentRoutingReach,
} from "./CostRoutingControl";

afterEach(cleanup);

describe("isCostRoutingSession", () => {
  it("matches any top-level session with an agent name", () => {
    expect(isCostRoutingSession({ agentName: "polly", parentSessionId: null })).toBe(true);
    expect(isCostRoutingSession({ agentName: "debby", parentSessionId: null })).toBe(true);
  });

  it("rejects a child session", () => {
    expect(isCostRoutingSession({ agentName: "polly", parentSessionId: "conv_parent987" })).toBe(
      false,
    );
  });

  it("rejects a session with no agent name", () => {
    expect(isCostRoutingSession({ agentName: null, parentSessionId: null })).toBe(false);
  });

  it("rejects a missing session", () => {
    expect(isCostRoutingSession(null)).toBe(false);
    expect(isCostRoutingSession(undefined)).toBe(false);
  });
});

describe("isSubagentRoutingSession", () => {
  const top = { agentName: "claude-native-ui", parentSessionId: null };

  it("matches a Smart Routing session of either family, pinned or auto", () => {
    // Pinned Smart Routing on either family: the launch starts the
    // spawn-routing endpoint, and on codex that advertisement is what turns on
    // the generated hooks.json gate and the routed-spawn pre-approvals.
    for (const harness of ["claude-native", "codex-native"]) {
      expect(isSubagentRoutingSession({ ...top, harness, costControlModeOverride: "on" })).toBe(
        true,
      );
    }
    // Auto-harness may land on either family, and both install the apparatus.
    expect(isSubagentRoutingSession({ ...top, harness: "auto" })).toBe(true);
    for (const harness of ["claude-native", "codex-native"]) {
      expect(
        isSubagentRoutingSession({
          ...top,
          harness,
          labels: { [AUTO_HARNESS_LABEL_KEY]: "1" },
        }),
      ).toBe(true);
    }
  });

  it("rejects a plain native session, where nothing would read the switch", () => {
    // No Smart Routing at create means no endpoint, no spawn gate and no
    // pre-approvals, so flipping the switch afterwards would change nothing.
    for (const harness of ["claude-native", "codex-native"]) {
      expect(isSubagentRoutingSession({ ...top, harness })).toBe(false);
      expect(isSubagentRoutingSession({ ...top, harness, costControlModeOverride: "off" })).toBe(
        false,
      );
    }
  });

  it("matches a native session created with sub-agent routing on its own model", () => {
    // The create stamps the label and every launch installs the spawn gate,
    // while the session's own routing stays off.
    for (const harness of ["claude-native", "codex-native"]) {
      expect(
        isSubagentRoutingSession({
          ...top,
          harness,
          labels: { [SUBAGENT_ROUTING_LABEL_KEY]: "1" },
        }),
      ).toBe(true);
    }
    // A native wrapper with no spawn hook has nothing to install.
    expect(
      isSubagentRoutingSession({
        ...top,
        harness: "cursor-native",
        labels: { [SUBAGENT_ROUTING_LABEL_KEY]: "1" },
      }),
    ).toBe(false);
  });

  it("matches non-native sessions whatever their harness (spawns go through create)", () => {
    // An SDK/bundle agent spawns children through the session-create path, which
    // routes off this switch regardless of the harness the parent runs.
    expect(isSubagentRoutingSession({ ...top, harness: "pi" })).toBe(true);
    // Codex-family but not native, and unrouted: its children still route off
    // this switch, because they are created rather than spawned in-harness.
    expect(isSubagentRoutingSession({ ...top, harness: "codex" })).toBe(true);
    expect(isSubagentRoutingSession({ ...top, harness: "openai-agents" })).toBe(true);
    expect(isSubagentRoutingSession({ ...top, harness: "not-a-real-harness" })).toBe(true);
    expect(isSubagentRoutingSession({ ...top, harness: null })).toBe(true);
  });

  it("rejects native wrappers with no native-subagent router", () => {
    // Native terminal CLIs spawn in-harness through the hook, which only
    // Claude/Codex implement — the knob would be inert elsewhere.
    expect(isSubagentRoutingSession({ ...top, harness: "cursor-native" })).toBe(false);
    expect(isSubagentRoutingSession({ ...top, harness: "pi-native" })).toBe(false);
    expect(
      isSubagentRoutingSession({
        ...top,
        harness: "pi",
        labels: { "omnigent.wrapper": "cursor-native-ui" },
      }),
    ).toBe(false);
  });

  it("rejects a child session even on a routable harness", () => {
    expect(
      isSubagentRoutingSession({
        agentName: "claude-native-ui",
        parentSessionId: "conv_parent987",
        harness: "claude-native",
        costControlModeOverride: "on",
      }),
    ).toBe(false);
  });

  it("rejects a missing session", () => {
    expect(isSubagentRoutingSession(null)).toBe(false);
    expect(isSubagentRoutingSession(undefined)).toBe(false);
  });
});

describe("subagentRoutingReach", () => {
  const top = { agentName: "claude-native-ui", parentSessionId: null };

  it("covers every sub-agent where the launch installed the spawn gate", () => {
    const session = {
      ...top,
      harness: "claude-native",
      labels: { [SUBAGENT_ROUTING_LABEL_KEY]: "1" },
    };
    // The control stays while the switch is off, so it can be turned back on.
    for (const override of ["on", "off", null] as const) {
      expect(subagentRoutingReach(session, override)).toBe("spawns");
    }
    expect(subagentRoutingReach({ ...top, harness: "pi" }, null)).toBe("spawns");
  });

  it("covers child sessions only on a plain native session switched on afterwards", () => {
    for (const harness of ["claude-native", "codex-native"]) {
      expect(subagentRoutingReach({ ...top, harness }, "on")).toBe("child-sessions");
      // Off or unset there is nothing to say and nothing to turn off.
      expect(subagentRoutingReach({ ...top, harness }, "off")).toBeNull();
      expect(subagentRoutingReach({ ...top, harness }, null)).toBeNull();
    }
  });

  it("offers no control where nothing routes", () => {
    expect(subagentRoutingReach({ ...top, harness: "cursor-native" }, "on")).toBeNull();
    expect(
      subagentRoutingReach({ ...top, parentSessionId: "conv_parent987", harness: "pi" }, "on"),
    ).toBeNull();
    expect(subagentRoutingReach(null, "on")).toBeNull();
  });
});

describe("shortModelName", () => {
  it("collapses Claude ids to their family token", () => {
    expect(shortModelName("databricks-claude-haiku-4-5")).toBe("haiku");
    expect(shortModelName("databricks-claude-sonnet-4-6")).toBe("sonnet");
    expect(shortModelName("claude-opus-4-7")).toBe("opus");
  });

  it("strips the databricks- prefix from non-Claude ids", () => {
    expect(shortModelName("databricks-gpt-5-4-mini")).toBe("gpt-5-4-mini");
  });

  it("passes unrecognized ids through unchanged (fallback to the id)", () => {
    expect(shortModelName("gpt-5.4")).toBe("gpt-5.4");
  });
});
