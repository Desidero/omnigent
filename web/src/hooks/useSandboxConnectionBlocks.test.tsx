import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FALLBACK_SERVER_INFO, type ServerInfo } from "@/lib/capabilities";
import { authenticatedFetch } from "@/lib/identity";
import {
  sandboxConnectionBlockMessage,
  useSandboxConnectionBlocks,
} from "./useSandboxConnectionBlocks";

vi.mock("@/lib/identity", () => ({ authenticatedFetch: vi.fn() }));

const fetchMock = vi.mocked(authenticatedFetch);

function info(overrides: Partial<ServerInfo>): ServerInfo {
  return {
    ...FALLBACK_SERVER_INFO,
    sandbox_provider_owner_connections: { databricks: "databricks" },
    enabled_connections: ["databricks"],
    ...overrides,
  };
}

function respond(status: number, body: unknown) {
  fetchMock.mockResolvedValue({
    ok: status < 400,
    status,
    json: async () => body,
  } as unknown as Response);
}

function renderBlocks(serverInfo: ServerInfo | "loading") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useSandboxConnectionBlocks(serverInfo, "alice"), { wrapper });
  return { ...hook, client };
}

beforeEach(() => fetchMock.mockReset());

describe("useSandboxConnectionBlocks", () => {
  it("blocks a provider whose owner has not connected, with a way to connect", async () => {
    respond(200, { enabled: true, connected: false });
    const { result } = renderBlocks(info({}));
    await waitFor(() =>
      expect([...result.current]).toEqual([
        ["databricks", { connection: "databricks", canConnect: true }],
      ]),
    );
    expect(fetchMock).toHaveBeenCalledWith("/v1/connections/databricks/status");
  });

  it("blocks nothing once the owner is connected", async () => {
    respond(200, { enabled: true, connected: true });
    const { result } = renderBlocks(info({}));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(result.current.size).toBe(0));
  });

  it.each([
    ["the status request fails", 500, {}],
    ["the status has no connected flag", 200, { enabled: true }],
  ])("blocks nothing when %s, leaving the refusal to the server", async (_case, status, body) => {
    respond(status, body);
    const { result, client } = renderBlocks(info({}));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(result.current.size).toBe(0);
  });

  it("blocks a provider without asking when the server has no such connection", () => {
    const { result } = renderBlocks(info({ enabled_connections: ["github"] }));
    expect([...result.current]).toEqual([
      ["databricks", { connection: "databricks", canConnect: false }],
    ]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["no provider launches as its owner", info({ sandbox_provider_owner_connections: {} })],
    ["server info is still loading", "loading" as const],
  ])("asks nothing and blocks nothing when %s", (_case, serverInfo) => {
    const { result } = renderBlocks(serverInfo);
    expect(result.current.size).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the same map while the answer is unchanged", async () => {
    respond(200, { enabled: true, connected: false });
    const { result, rerender } = renderBlocks(info({}));
    await waitFor(() => expect(result.current.size).toBe(1));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});

describe("sandboxConnectionBlockMessage", () => {
  it("names the account to connect or says the server has none", () => {
    expect(
      sandboxConnectionBlockMessage("Databricks Sandbox", {
        connection: "databricks",
        canConnect: true,
      }),
    ).toBe("Connect Databricks to use Databricks Sandbox");
    expect(
      sandboxConnectionBlockMessage("Databricks Sandbox", {
        connection: "databricks",
        canConnect: false,
      }),
    ).toBe("Databricks Sandbox is unavailable: this server has no Databricks connection set up");
  });
});
