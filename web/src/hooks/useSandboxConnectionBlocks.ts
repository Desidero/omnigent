import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import type { ServerInfo } from "@/lib/capabilities";
import { getOmnigentServerIdentity } from "@/lib/host";
import { authenticatedFetch } from "@/lib/identity";

/** Why a sandbox provider cannot launch for the signed-in user. */
export interface SandboxConnectionBlock {
  /** The connection the provider launches as, e.g. ``"databricks"``. */
  connection: string;
  /** False when the server has no such connection set up, so the user cannot fix it. */
  canConnect: boolean;
}

async function fetchConnected(connection: string): Promise<boolean | null> {
  const response = await authenticatedFetch(
    `/v1/connections/${encodeURIComponent(connection)}/status`,
  );
  if (!response.ok) throw new Error(`Connection status failed: ${response.status}`);
  const body: unknown = await response.json();
  const connected = (body as { connected?: unknown } | null)?.connected;
  return typeof connected === "boolean" ? connected : null;
}

/**
 * The sandbox providers the signed-in user cannot launch yet, keyed by provider.
 *
 * A provider that launches as its owner (``sandbox_provider_owner_connections``
 * in ``/v1/info``) is blocked when the server has no such connection, or when
 * the user's status says they have not connected. An unknown status (loading,
 * failed) blocks nothing: the server refuses the launch either way.
 */
export function useSandboxConnectionBlocks(
  info: ServerInfo | "loading",
  user: string | null,
): ReadonlyMap<string, SandboxConnectionBlock> {
  const required = useMemo(
    () => (info === "loading" ? [] : Object.entries(info.sandbox_provider_owner_connections ?? {})),
    [info],
  );
  const offered = info === "loading" ? [] : info.enabled_connections;
  const statuses = useQueries({
    queries: required.map(([, connection]) => ({
      queryKey: ["connection-status", user, connection, getOmnigentServerIdentity()] as const,
      queryFn: () => fetchConnected(connection),
      enabled: offered.includes(connection),
    })),
  });
  const blockedKey = JSON.stringify(
    required.flatMap(([provider, connection], index) => {
      if (!offered.includes(connection)) return [[provider, { connection, canConnect: false }]];
      return statuses[index]?.data === false ? [[provider, { connection, canConnect: true }]] : [];
    }),
  );
  return useMemo(
    () => new Map<string, SandboxConnectionBlock>(JSON.parse(blockedKey)),
    [blockedKey],
  );
}

/** What to tell the user about a blocked provider, e.g. for "Databricks Sandbox". */
export function sandboxConnectionBlockMessage(
  sandboxLabel: string,
  block: SandboxConnectionBlock,
): string {
  const account = block.connection.charAt(0).toUpperCase() + block.connection.slice(1);
  return block.canConnect
    ? `Connect ${account} to use ${sandboxLabel}`
    : `${sandboxLabel} is unavailable: this server has no ${account} connection set up`;
}
