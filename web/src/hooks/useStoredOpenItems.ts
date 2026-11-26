// A session's stored open items, on servers that store them (`/v1/info`
// `open_items`). Kept live by `session.open_items.changed` (chatStore
// invalidates the query) and read again whenever the session's stream reopens.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useMemo } from "react";
import { useOpenItemCount, useDismissedItems } from "@/components/chat/OpenItemsPanel";
import { showToast } from "@/components/ui/toast";
import { useServerInfo } from "@/lib/CapabilitiesContext";
import {
  ItemLabelIndexContext,
  ItemLabelSessionContext,
  type ItemLabelEntry,
  type ItemLabelIndex,
} from "@/lib/itemLabels";
import {
  countOpenRows,
  fetchStoredOpenItems,
  importChatItems,
  openItemRows,
  openItemsKey,
  refreshStoredOpenItems,
  updateStoredOpenItems,
  withWrittenItems,
  type ChatItemImport,
  type OpenItemUpdate,
  type StoredOpenItem,
} from "@/lib/openItems";
import { isSessionStreamOpen, subscribeSessionStreams } from "@/lib/sessionStreamSignals";
import { isTempConvId } from "@/lib/tempConversationId";

/** Whether the server stores open items; false while `/v1/info` loads and on older servers. */
export function useOpenItemsAvailable(): boolean {
  const info = useServerInfo();
  return info !== "loading" && info.open_items === true;
}

/**
 * The session's stored items in label order. Null on servers without the
 * store, until the first read lands, and when it fails: callers then show
 * the chat's labels alone, as before the store existed.
 */
export function useStoredOpenItems(
  rawSessionId: string | null | undefined,
): readonly StoredOpenItem[] | null {
  const queryClient = useQueryClient();
  const available = useOpenItemsAvailable();
  const sessionId = rawSessionId && !isTempConvId(rawSessionId) ? rawSessionId : undefined;
  const active = available && sessionId !== undefined;
  const query = useQuery({
    queryKey: openItemsKey(sessionId),
    queryFn: () => fetchStoredOpenItems(sessionId!),
    enabled: active,
    // The session stream keeps it current.
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  useEffect(() => {
    if (!active) return;
    // Events missed while the stream was down: read the list again when it reopens.
    return subscribeSessionStreams((id) => {
      if (id === sessionId && isSessionStreamOpen(id)) {
        refreshStoredOpenItems(queryClient, sessionId);
      }
    });
  }, [active, sessionId, queryClient]);
  return active && query.data ? query.data : null;
}

/**
 * Close, reopen or retopic stored items. The written items replace their
 * cached copies at once; a refused write says why in a toast.
 */
export function useUpdateStoredOpenItems(sessionId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (updates: OpenItemUpdate[]) => {
      if (!sessionId) throw new Error("No session selected");
      return updateStoredOpenItems(sessionId, updates);
    },
    onSuccess: (results) => {
      if (!sessionId) return;
      queryClient.setQueryData<StoredOpenItem[]>(openItemsKey(sessionId), (items) =>
        withWrittenItems(items, results),
      );
      const refused = results.find((result) => "error" in result);
      if (refused && "error" in refused) {
        showToast(`Couldn't change ${refused.label}: ${refused.error.message}`);
      }
    },
    onError: (error) => showToast(`Couldn't change the item: ${error.message}`),
  });
}

/** Store the chat's own labels under their labels; says how it went in a toast. */
export function useImportChatItems(sessionId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (items: ChatItemImport[]) => {
      if (!sessionId) throw new Error("No session selected");
      return importChatItems(sessionId, items);
    },
    onSuccess: (results) => {
      if (!sessionId) return;
      queryClient.setQueryData<StoredOpenItem[]>(openItemsKey(sessionId), (items) =>
        withWrittenItems(items, results),
      );
      const imported = results.filter((result) => "item" in result).length;
      const refused = results.length - imported;
      showToast(
        `Imported ${imported} item${imported === 1 ? "" : "s"} from the chat` +
          (refused > 0 ? `; ${refused} already stored or refused` : ""),
      );
    },
    onError: (error) => showToast(`Couldn't import the chat's items: ${error.message}`),
  });
}

/**
 * The header button's badge: open items that wait on the user. With stored
 * items, stored ones count by their stored status and the chat's own labels
 * as before; otherwise the chat's count alone.
 */
export function useSessionOpenItemCount(): number {
  const chatCount = useOpenItemCount();
  const index = useContext(ItemLabelIndexContext);
  const sessionId = useContext(ItemLabelSessionContext);
  const stored = useStoredOpenItems(sessionId);
  const { dismissed } = useDismissedItems(sessionId);
  return useMemo(
    () => (stored ? countOpenRows(openItemRows(index, stored, dismissed)) : chatCount),
    [stored, index, dismissed, chatCount],
  );
}

/**
 * The index the header button decides whether to show from: `index`, plus
 * stored items none of whose messages are loaded, so a long session's items
 * stay one tap away. Their entries only count; nothing renders them.
 */
export function useSessionItemsIndex(index: ItemLabelIndex | null): ItemLabelIndex | null {
  const stored = useStoredOpenItems(useContext(ItemLabelSessionContext));
  return useMemo(() => {
    const unloaded = (stored ?? []).filter(
      (item) => item.kind !== "link" && !index?.items.has(item.label),
    );
    if (unloaded.length === 0) return index;
    const items = new Map<string, ItemLabelEntry>(index?.items);
    for (const item of unloaded) {
      const source = {
        messageId: "",
        role: "assistant" as const,
        text: `[${item.label}] ${item.title}`,
      };
      items.set(item.label, {
        label: item.label,
        source,
        closedBy: item.status === "closed" ? source : null,
        lastMention: source,
        messageCount: 1,
      } as ItemLabelEntry);
    }
    return { enabled: true, items, latestReply: index?.latestReply ?? null };
  }, [index, stored]);
}
