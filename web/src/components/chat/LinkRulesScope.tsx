import { useMemo } from "react";
import { useLinkRules } from "@/hooks/useLinkRules";
import { type PullRequestInfo, usePullRequestInfo } from "@/hooks/usePullRequests";
import { compileLinkRules, type GithubLinkTarget, LinkRuleMatchersContext } from "@/lib/linkRules";

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
 * Where the session's `#123` references link, from its git provider info: the
 * repository's own host (never assumed to be github.com), or `null` when the
 * session has no GitHub repository or its host isn't known yet.
 */
export function githubLinkTarget(info: PullRequestInfo | undefined): GithubLinkTarget | null {
  if (!info?.available) return null;
  // An absent provider is a host that predates the field, which serves GitHub.
  if (info.provider !== undefined && info.provider !== "github") return null;
  const repo = info.repo?.name_with_owner;
  if (!repo) return null;
  const sameRepo = (other: string) => other.toLowerCase() === repo.toLowerCase();
  const known = (info.prs ?? []).filter((pr) => sameRepo(pr.repository));
  const origin =
    originOf(info.repo?.url) ?? originOf(info.pr?.url) ?? originOf(known[0]?.url) ?? null;
  if (origin === null) return null;
  const pullNumbers = new Set(known.map((pr) => pr.number));
  if (info.pr) pullNumbers.add(info.pr.number);
  return { origin, repo, pullNumbers };
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
  const { data: info } = usePullRequestInfo(sessionId ?? undefined);
  const github = useMemo(() => githubLinkTarget(info), [info]);
  const matchers = useMemo(
    () => compileLinkRules(settings?.rules ?? [], github),
    [settings, github],
  );
  return (
    <LinkRuleMatchersContext.Provider value={matchers}>{children}</LinkRuleMatchersContext.Provider>
  );
}
