import { describe, expect, it } from "vitest";
import type { PullRequestAssociation, PullRequestInfo } from "@/hooks/usePullRequests";
import { githubLinkTarget } from "./LinkRulesScope";

function info(fields: Partial<PullRequestInfo>): PullRequestInfo {
  return { object: "session.github.info", available: true, provider: "github", ...fields };
}

function association(number: number, repository: string, url: string): PullRequestAssociation {
  return { url, host: new URL(url).host, repository, number, relationship: "created" };
}

describe("githubLinkTarget", () => {
  it("uses the host the repository reports, not github.com", () => {
    expect(
      githubLinkTarget(
        info({ repo: { name_with_owner: "acme/app", url: "https://ghe.example.com/acme/app" } }),
      ),
    ).toEqual({ origin: "https://ghe.example.com", repo: "acme/app", pullNumbers: new Set() });
  });

  it("falls back to a known pull request's host and collects pull numbers", () => {
    const target = githubLinkTarget(
      info({
        repo: { name_with_owner: "acme/app" },
        prs: [
          association(5, "acme/app", "https://ghe.example.com/acme/app/pull/5"),
          association(9, "other/lib", "https://ghe.example.com/other/lib/pull/9"),
        ],
      }),
    );
    expect(target?.origin).toBe("https://ghe.example.com");
    expect([...(target?.pullNumbers ?? [])]).toEqual([5]);
  });

  it.each([
    ["no info", undefined],
    ["not a repo", info({ available: false })],
    ["another provider", info({ provider: "gitlab", repo: { name_with_owner: "a/b" } })],
    ["no repository", info({ repo: null })],
    ["an unknown host", info({ repo: { name_with_owner: "acme/app" } })],
    ["a non-http URL", info({ repo: { name_with_owner: "acme/app", url: "javascript:alert(1)" } })],
  ])("is null with %s", (_case, value) => {
    expect(githubLinkTarget(value)).toBe(null);
  });
});
