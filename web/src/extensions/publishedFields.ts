import { useQuery } from "@tanstack/react-query";
import { authenticatedFetch } from "@/lib/identity";
import { SESSION_PUBLISHED_FIELDS_KEY } from "@/lib/sessionListCache";
import { apiErrorFromResponse } from "@/lib/sessionsApi";
import type { PublishedFields } from "./types";

async function fetchPublishedFields(sessionId: string): Promise<PublishedFields> {
  const query = new URLSearchParams({
    include_items: "false",
    include_liveness: "false",
    include_usage: "false",
  });
  const response = await authenticatedFetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}?${query}`,
  );
  if (!response.ok) throw await apiErrorFromResponse(response);
  const body = (await response.json()) as { published_fields?: PublishedFields };
  return body.published_fields ?? {};
}

/**
 * One session's published extension fields, fetched only when `sessionId` is
 * set. Live updates come from this client's commands and the session-updates
 * stream's `changed` frames for watched sessions; otherwise it refetches when
 * next mounted once it is 30 seconds old.
 */
export function useSessionPublishedFields(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: [SESSION_PUBLISHED_FIELDS_KEY, sessionId],
    queryFn: () => fetchPublishedFields(sessionId as string),
    enabled: Boolean(sessionId),
    staleTime: 30_000,
  }).data;
}
