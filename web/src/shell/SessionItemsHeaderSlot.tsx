// The session header's spot for the open-items button. The transcript owns
// the button (it derives the items) and portals it here; a surface without the
// header has no slot, and the transcript keeps its Open items bar instead.

import { useCallback, useSyncExternalStore } from "react";

const hosts = new Map<string, HTMLElement>();
const listeners = new Set<() => void>();

function setHost(sessionId: string, element: HTMLElement | null): void {
  if (element) hosts.set(sessionId, element);
  else hosts.delete(sessionId);
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Where `sessionId`'s open-items button renders in the header, or null without one. */
export function useSessionItemsHeaderHost(
  sessionId: string | null | undefined,
): HTMLElement | null {
  return useSyncExternalStore(subscribe, () => (sessionId ? (hosts.get(sessionId) ?? null) : null));
}

/** The header slot `sessionId`'s transcript fills; takes no room while empty. */
export function SessionItemsHeaderSlot({ sessionId }: { sessionId: string }) {
  const register = useCallback(
    (element: HTMLDivElement | null) => setHost(sessionId, element),
    [sessionId],
  );
  return (
    <div
      ref={register}
      data-testid="session-items-slot"
      className="no-drag flex items-center empty:hidden"
    />
  );
}
