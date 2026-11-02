import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { showToast } from "@/components/ui/toast";
import { authenticatedFetch } from "@/lib/identity";
import { overlayLabelIntoCaches } from "@/lib/sessionListCache";
import { apiErrorFromResponse } from "@/lib/sessionsApi";
import type { ExtensionLabelDeclaration } from "./types";

export const LABEL_WRITE_TIMEOUT_MS = 8_000;

/**
 * Write one declared label through `PATCH /v1/sessions/{id}` as the viewer.
 * An empty value clears it: the server deletes declared labels on "".
 */
export async function writeSessionLabel(id: string, key: string, value: string): Promise<void> {
  const response = await authenticatedFetch(`/v1/sessions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ labels: { [key]: value } }),
    // A hung request would otherwise hold back every later write to this key.
    signal: AbortSignal.timeout(LABEL_WRITE_TIMEOUT_MS),
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
}

async function readSessionLabel(id: string, key: string): Promise<string> {
  const response = await authenticatedFetch(`/v1/sessions/${encodeURIComponent(id)}/labels`, {
    signal: AbortSignal.timeout(LABEL_WRITE_TIMEOUT_MS),
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
  const { labels } = (await response.json()) as { labels?: Record<string, string> };
  return labels && Object.hasOwn(labels, key) ? labels[key] : "";
}

// Writes to one session's key run in order, so the server keeps the last one sent.
interface LabelWrites {
  tail: Promise<void>;
  latest: number;
  /** A write failed or timed out; an aborted request may still land later. */
  uncertain: boolean;
}
const labelWrites = new Map<string, LabelWrites>();
let writeCount = 0;

/**
 * Write a label and paint it on every cached copy of the row. If any write to
 * the key failed, the last one to settle shows what the server holds.
 */
export async function writeSessionLabelOptimistically(
  queryClient: QueryClient,
  sessionId: string,
  key: string,
  value: string,
): Promise<void> {
  const slot = JSON.stringify([sessionId, key]);
  const writes = labelWrites.get(slot) ?? {
    tail: Promise.resolve(),
    latest: 0,
    uncertain: false,
  };
  const write = ++writeCount;
  writes.latest = write;
  labelWrites.set(slot, writes);
  overlayLabelIntoCaches(queryClient, sessionId, key, value);
  const request = writes.tail.then(() => writeSessionLabel(sessionId, key, value));
  writes.tail = request.then(
    () => undefined,
    () => undefined,
  );
  // A newer write to the slot takes over showing the server's value.
  const stillLatest = () => writes.latest === write && labelWrites.get(slot) === writes;
  // The last write to settle shows the server's value if any write failed.
  const settle = async () => {
    if (!stillLatest()) return;
    if (!writes.uncertain) {
      labelWrites.delete(slot);
      return;
    }
    // Stay registered while reading back: a newer write joins this entry, keeps
    // `uncertain`, and supersedes this read-back.
    let serverValue: string | undefined;
    try {
      serverValue = await readSessionLabel(sessionId, key);
    } catch {
      serverValue = undefined;
    }
    if (!stillLatest()) return;
    labelWrites.delete(slot);
    if (serverValue !== undefined) {
      overlayLabelIntoCaches(queryClient, sessionId, key, serverValue);
    } else {
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["project-sessions"] });
    }
  };
  try {
    await request;
  } catch (error) {
    writes.uncertain = true;
    await settle();
    throw error;
  }
  await settle();
}

/** The row menu's declared-label write, with core's failure toast. */
export function useSetSessionLabel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      label,
      value,
    }: {
      sessionId: string;
      label: ExtensionLabelDeclaration;
      value: string;
    }) => writeSessionLabelOptimistically(queryClient, sessionId, label.key, value),
    onError: (error, { label }) => {
      const detail = error instanceof Error && error.message ? `: ${error.message}` : "";
      showToast(`Couldn't update ${label.title}${detail}`);
    },
  });
}
