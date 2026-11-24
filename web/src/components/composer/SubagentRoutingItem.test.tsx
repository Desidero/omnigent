import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SUBAGENT_ROUTING_LABEL_KEY } from "@/components/CostRoutingControl";
import { DropdownMenu, DropdownMenuContent } from "@/components/ui/dropdown-menu";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import type { Session } from "@/lib/types";
import { useChatStore } from "@/store/chatStore";
import { SubagentRoutingItem } from "./SubagentRoutingItem";

const sessionRead = vi.hoisted(() => ({ session: null as unknown, reads: 0 }));
vi.mock("@/hooks/useSession", () => ({
  useSession: () => {
    sessionRead.reads += 1;
    return { session: sessionRead.session, isLoading: false, error: null };
  },
}));

const initialState = useChatStore.getState();

afterEach(() => {
  cleanup();
  useChatStore.setState(initialState, true);
  sessionRead.session = null;
  sessionRead.reads = 0;
});

const ROUTING_SERVER = { ...FALLBACK_SERVER_INFO, smart_routing_enabled: true };

function nativeSession(labels: Record<string, string> = {}): Partial<Session> {
  return { agentName: "claude-native-ui", parentSessionId: null, harness: "claude-native", labels };
}

function renderItem({
  session,
  override = null,
  info = ROUTING_SERVER,
  onChange = () => {},
}: {
  session: Partial<Session> | null;
  override?: "on" | "off" | null;
  info?: typeof FALLBACK_SERVER_INFO;
  onChange?: (mode: "on" | "off") => void;
}) {
  sessionRead.session = session;
  useChatStore.setState({ conversationId: "conv_1", subagentRoutingOverride: override });
  return render(
    <CapabilitiesProvider info={info}>
      <DropdownMenu open>
        <DropdownMenuContent>
          <SubagentRoutingItem
            sessionId={undefined}
            conversationId="conv_1"
            disabled={false}
            onChange={onChange}
          />
        </DropdownMenuContent>
      </DropdownMenu>
    </CapabilitiesProvider>,
  );
}

const item = () => screen.queryByTestId("composer-agent-subagent-routing");

it("toggles sub-agent routing on a native session created with it", () => {
  const onChange = vi.fn();
  renderItem({
    session: nativeSession({ [SUBAGENT_ROUTING_LABEL_KEY]: "1" }),
    override: "on",
    onChange,
  });

  expect(item()?.getAttribute("aria-checked")).toBe("true");
  expect(item()?.getAttribute("data-subagent-routing-reach")).toBe("spawns");
  expect(item()?.textContent).toBe("Route sub-agents");
  fireEvent.click(item()!);
  expect(onChange).toHaveBeenCalledWith("off");
});

it("keeps the control after the switch is turned off, so it can come back on", () => {
  const onChange = vi.fn();
  renderItem({
    session: nativeSession({ [SUBAGENT_ROUTING_LABEL_KEY]: "1" }),
    override: "off",
    onChange,
  });

  expect(item()?.getAttribute("aria-checked")).toBe("false");
  fireEvent.click(item()!);
  expect(onChange).toHaveBeenCalledWith("on");
});

it("says so when only child sessions are routed", () => {
  // A plain native launch has no spawn gate; the switch was turned on later.
  renderItem({ session: nativeSession(), override: "on" });

  expect(item()?.getAttribute("data-subagent-routing-reach")).toBe("child-sessions");
  expect(item()?.textContent).toContain("Child sessions only");
});

it("offers nothing on a plain native session", () => {
  renderItem({ session: nativeSession(), override: null });
  expect(item()).toBeNull();
});

it("reads no session on a server that cannot route", () => {
  renderItem({
    session: nativeSession({ [SUBAGENT_ROUTING_LABEL_KEY]: "1" }),
    override: "on",
    info: FALLBACK_SERVER_INFO,
  });
  expect(item()).toBeNull();
  expect(sessionRead.reads).toBe(0);
});
