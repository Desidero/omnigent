import { useMemo } from "react";
import { useLinkRules } from "@/hooks/useLinkRules";
import {
  normalizePullRequestInfo,
  type PullRequestInfo,
  usePullRequestInfo,
} from "@/hooks/usePullRequests";
import {
  compileLinkRules,
  LinkRuleMatchersContext,
  type SessionGitRepository,
} from "@/lib/linkRules";

function originOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.origin : null;
  } catch {
    return null;
  }
}

/**
 * The repository a session's chat references link to, from its git info: the
 * provider the server resolved and the repository's own host (never assumed
 * from the provider), or `null` when the session has no repository or its
 * host isn't known yet.
 */
export function sessionGitRepository(
  info: PullRequestInfo | undefined,
): SessionGitRepository | null {
  if (!info?.available) return null;
  // An absent provider is a host that predates the field, which serves GitHub.
  const { provider } = normalizePullRequestInfo(info);
  const repository = info.repo?.name_with_owner;
  if (!repository) return null;
  const sameRepository = (other: string) => other.toLowerCase() === repository.toLowerCase();
  const known = (info.prs ?? []).filter((pr) => sameRepository(pr.repository));
  const origin =
    originOf(info.repo?.url) ?? originOf(info.pr?.url) ?? originOf(known[0]?.url) ?? null;
  if (origin === null) return null;
  const pullNumbers = new Set(known.map((pr) => pr.number));
  if (info.pr) pullNumbers.add(info.pr.number);
  return { provider, origin, repository, pullNumbers };
}

/**
 * {@link sessionGitRepository} with a stable identity while its fields are
 * unchanged: the git info polls, and new matchers would re-parse every message.
 */
function useSessionGitRepository(sessionId: string | null): SessionGitRepository | null {
  const { data: info } = usePullRequestInfo(sessionId ?? undefined);
  const repository = sessionGitRepository(info);
  const serialized =
    repository === null
      ? null
      : JSON.stringify({
          ...repository,
          pullNumbers: [...repository.pullNumbers].sort((a, b) => a - b),
        });
  return useMemo(() => {
    if (serialized === null) return null;
    const parsed = JSON.parse(serialized) as Omit<SessionGitRepository, "pullNumbers"> & {
      pullNumbers: number[];
    };
    return { ...parsed, pullNumbers: new Set(parsed.pullNumbers) };
  }, [serialized]);
}

/** Compiles the user's link rules for the transcript of `sessionId`. */
export function LinkRulesScope({
  sessionId,
  children,
}: {
  sessionId: string | null;
  children: React.ReactNode;
}) {
  const { data: settings } = useLinkRules();
  const repository = useSessionGitRepository(sessionId);
  const matchers = useMemo(
    () => compileLinkRules(settings?.rules ?? [], repository),
    [settings, repository],
  );
  return (
    <LinkRuleMatchersContext.Provider value={matchers}>{children}</LinkRuleMatchersContext.Provider>
  );
}
