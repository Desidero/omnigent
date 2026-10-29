import { describe, expect, it } from "vitest";
import {
  checkGitHost,
  compileLinkPattern,
  compileLinkRules,
  findLinks,
  type GitLinkTarget,
  type GitProviderId,
  gitReferenceUrl,
  type LinkRule,
  linkRuleError,
  linkRuleErrors,
  parseSessionReference,
  remarkLinkRules,
  type SessionGitRepository,
  sessionGitRule,
} from "./linkRules";

function urlRule(pattern: string, url: string, name = "Rule"): LinkRule {
  return { name, kind: "url", pattern, url, enabled: true };
}

function gitRule(name: string, provider: GitProviderId, host: string, enabled = true): LinkRule {
  return { name, kind: "git", provider, host, pattern: "", url: null, enabled };
}

const GITHUB_RULE = gitRule("GitHub", "github", "github.com");
const GITLAB_RULE = gitRule("GitLab", "gitlab", "gitlab.com");
const AZURE_RULE = gitRule("Azure DevOps", "azure_devops", "dev.azure.com");
const GIT_DEFAULTS = [GITHUB_RULE, GITLAB_RULE, AZURE_RULE];

function repo(
  provider: string | null,
  origin: string,
  repository: string,
  pullNumbers: number[] = [],
): SessionGitRepository {
  return { provider, origin, repository, pullNumbers: new Set(pullNumbers) };
}

const GITHUB_SESSION = repo("github", "https://github.com", "acme/app", [7]);
const GITLAB_SESSION = repo("gitlab", "https://gitlab.com", "acme/backend/api");

function links(text: string, rules: LinkRule[], session: SessionGitRepository | null = null) {
  return findLinks(text, compileLinkRules(rules, session)).map(({ start, end, href }) => ({
    text: text.slice(start, end),
    href,
  }));
}

describe("compileLinkPattern", () => {
  it.each([
    ["BST-{num}", String.raw`BST\-(\d{1,10})`, 1],
    ["{key}-{num}", String.raw`([A-Z][A-Z0-9]{1,9})\-(\d{1,10})`, 2],
    ["/(ENG-\\d+)/", String.raw`(ENG-\d{1,64})`, 1],
    ["/x.*y/", "x.{0,64}y", 0],
  ])("compiles %s", (pattern, source, groups) => {
    const compiled = compileLinkPattern(pattern);
    expect(compiled.source).toBe(source);
    expect(compiled.groupCount).toBe(groups);
  });

  it.each([
    ["", "required"],
    ["BST", "needs a placeholder"],
    ["BST-{nope}", "unknown placeholder"],
    ["/(a+)+/", "repeated group"],
    ["/(a|b)*/", "repeated group"],
    ["/(a)\\1/", "backreferences"],
    ["/(?<name>a)/", "named groups"],
    ["/(?<=a)b/", "lookaround"],
    ["/(?i)a/", "inline flags"],
    ["/a{1000}/", "capped"],
    ["/[]a]/", "start of a [ ] class"],
    ["/(a/", "unbalanced ("],
    ["/a*/", "empty text"],
    ["/a+b+c+d+/", "at most 3 repeats"],
    ["x".repeat(201), "longer than"],
  ])("rejects %s", (pattern, message) => {
    expect(() => compileLinkPattern(pattern)).toThrow(message);
  });
});

describe("linkRuleError", () => {
  it.each([
    ["javascript:alert(1)//{num}", "https://"],
    ["data:text/html,{num}", "https://"],
    ["https://{num}.example.com/", "https://"],
    ["https://user@evil.example/{num}", "https://"],
    ["https://example.com/{3}", "no matching group"],
    ["https://example.com/{key}", "unknown placeholder"],
    ["https://example.com/ {num}", "spaces"],
  ])("rejects the template %s", (url, message) => {
    expect(linkRuleError(urlRule("BST-{num}", url))).toContain(message);
  });

  it("accepts a template on a fixed host", () => {
    expect(linkRuleError(urlRule("BST-{num}", "https://jira.example.com/browse/BST-{num}"))).toBe(
      null,
    );
  });

  it("refuses a pattern on a built-in kind", () => {
    expect(linkRuleError({ ...GITHUB_RULE, pattern: "#{num}" })).toContain("takes no pattern");
    expect(
      linkRuleError({
        name: "S",
        kind: "session",
        pattern: "",
        url: null,
        enabled: true,
        host: "x",
      }),
    ).toContain("belong to a git rule");
  });

  it("checks a git rule's provider and host", () => {
    expect(linkRuleError(gitRule("Ours", "gitlab", "GitLab.Example.com:8443"))).toBe(null);
    expect(linkRuleError({ ...GITLAB_RULE, provider: "bitbucket" as GitProviderId })).toContain(
      "provider: must be github, gitlab, azure_devops",
    );
    expect(linkRuleError({ ...GITLAB_RULE, host: "" })).toContain("host: required");
  });

  it.each([
    "https://gitlab.example.com",
    "gitlab.example.com/group",
    "user@gitlab.example.com",
    "user:pw@gitlab.example.com",
    "gitlab example.com",
    "gitlab.example.com:0",
    "gitlab.example.com:99999",
    "-gitlab.example.com",
    "gitlab..example.com",
    "a".repeat(254),
  ])("rejects the host %s", (host) => {
    expect(() => checkGitHost(host)).toThrow("host:");
  });

  it("reports repeated names and a built-in kind listed twice", () => {
    const session: LinkRule = { name: "S", kind: "session", pattern: "", url: null, enabled: true };
    expect(
      linkRuleErrors([
        urlRule("A-{num}", "https://e.com/{num}", "Jira"),
        urlRule("B-{num}", "https://e.com/{num}", "jira"),
        session,
        { ...session, name: "S2" },
      ]),
    ).toEqual([null, "two rules are named jira", null, "only one session rule"]);
    expect(
      linkRuleErrors([GITLAB_RULE, gitRule("Again", "gitlab", "GITLAB.com"), GITHUB_RULE]),
    ).toEqual([null, "two git rules are for gitlab.com", null]);
  });
});

describe("findLinks", () => {
  const jira = urlRule("BST-{num}", "https://jira.example.com/browse/BST-{num}", "Jira");

  it("links whole words only", () => {
    expect(links("BST-1, (BST-22) XBST-3 BST-4x", [jira])).toEqual([
      { text: "BST-1", href: "https://jira.example.com/browse/BST-1" },
      { text: "BST-22", href: "https://jira.example.com/browse/BST-22" },
    ]);
  });

  it("percent-encodes every captured value", () => {
    const rule = urlRule("/T:([^ ]{1,20})/", "https://e.example/q?x={1}");
    expect(links('T:"><img/onerror=1>', [rule])).toEqual([
      { text: 'T:"><img/onerror=1>', href: "https://e.example/q?x=%22%3E%3Cimg%2Fonerror%3D1%3E" },
    ]);
  });

  it("never yields a link off its template's host", () => {
    const rule = urlRule("/go:([a-z./:]{1,30})/", "https://safe.example/{1}");
    const [found] = links("go:javascript://evil.example", [rule]);
    expect(new URL(found.href).host).toBe("safe.example");
  });

  it("skips disabled and invalid rules", () => {
    expect(links("BST-1", [{ ...jira, enabled: false }])).toEqual([]);
    expect(links("BST-1", [{ ...jira, url: "javascript:x//{num}" }])).toEqual([]);
  });

  it("gives an overlap to the earliest match, then the first rule", () => {
    const wide = urlRule("{key}-{num}", "https://wide.example/{key}-{num}", "Wide");
    expect(links("BST-9", [jira, wide])[0].href).toContain("jira.example.com");
    expect(links("BST-9", [wide, jira])[0].href).toContain("wide.example");
  });

  it("turns session references into in-app hrefs", () => {
    const session: LinkRule = { name: "S", kind: "session", pattern: "", url: null, enabled: true };
    expect(links("see session:abc123def and session:abc123def/resp_9", [session])).toEqual([
      { text: "session:abc123def", href: "#omnigent-session-abc123def" },
      { text: "session:abc123def/resp_9", href: "#omnigent-session-abc123def/resp_9" },
    ]);
  });
});

describe("git references", () => {
  it("reads the kind from the word before the number", () => {
    expect(
      links("See issue #12, PR #34, pull #56 and merge request #78.", GIT_DEFAULTS, GITHUB_SESSION),
    ).toEqual([
      { text: "issue #12", href: "https://github.com/acme/app/issues/12" },
      { text: "PR #34", href: "https://github.com/acme/app/pull/34" },
      { text: "pull #56", href: "https://github.com/acme/app/pull/56" },
      { text: "merge request #78", href: "https://github.com/acme/app/pull/78" },
    ]);
  });

  it("sends a bare GitHub number to a known pull request, else the issue page", () => {
    expect(links("Fixes #12, see #7 and other/lib#3. a#4", GIT_DEFAULTS, GITHUB_SESSION)).toEqual([
      { text: "#12", href: "https://github.com/acme/app/issues/12" },
      { text: "#7", href: "https://github.com/acme/app/pull/7" },
      { text: "other/lib#3", href: "https://github.com/other/lib/issues/3" },
    ]);
  });

  it("ignores anchors, entities, identifiers and over-long numbers", () => {
    expect(
      links(
        "page.html#12 and https://x.test/a#3, C#5, &#123; bad; see #12345678 or ticket#4.",
        GIT_DEFAULTS,
        GITHUB_SESSION,
      ),
    ).toEqual([]);
  });

  it("links a GitLab session's issues, merge requests and own groups", () => {
    expect(
      links(
        "issue #3, !4, MR #5, acme/web!6, acme/frontend/web#7 and #8",
        GIT_DEFAULTS,
        GITLAB_SESSION,
      ),
    ).toEqual([
      { text: "issue #3", href: "https://gitlab.com/acme/backend/api/-/issues/3" },
      { text: "!4", href: "https://gitlab.com/acme/backend/api/-/merge_requests/4" },
      { text: "MR #5", href: "https://gitlab.com/acme/backend/api/-/merge_requests/5" },
      { text: "acme/web!6", href: "https://gitlab.com/acme/web/-/merge_requests/6" },
      { text: "acme/frontend/web#7", href: "https://gitlab.com/acme/frontend/web/-/issues/7" },
      { text: "#8", href: "https://gitlab.com/acme/backend/api/-/issues/8" },
    ]);
  });

  it("recognises `!` only where the session's provider writes requests that way", () => {
    expect(links("Merged !5 and #6.", GIT_DEFAULTS, GITHUB_SESSION).map((l) => l.text)).toEqual([
      "#6",
    ]);
  });

  it("maps an Azure DevOps session to work items and pull requests", () => {
    const azure = repo("azure_devops", "https://dev.azure.com", "org/project/repo");
    expect(links("#8, PR #9, !10 and org/other#2", GIT_DEFAULTS, azure)).toEqual([
      { text: "#8", href: "https://dev.azure.com/org/project/_workitems/edit/8" },
      { text: "PR #9", href: "https://dev.azure.com/org/project/_git/repo/pullrequest/9" },
      { text: "!10", href: "https://dev.azure.com/org/project/_git/repo/pullrequest/10" },
    ]);
  });

  it("uses a listed self-hosted host, and its provider's URL shapes", () => {
    const ours = gitRule("Our GitLab", "gitlab", "git.example.com");
    const session = repo(null, "https://git.example.com", "team/app");
    expect(links("#3 and !4", [...GIT_DEFAULTS, ours], session)).toEqual([
      { text: "#3", href: "https://git.example.com/team/app/-/issues/3" },
      { text: "!4", href: "https://git.example.com/team/app/-/merge_requests/4" },
    ]);
    // Unlisted, and no provider claims it: only GitHub's qualified form links.
    expect(links("#3 and acme/web#4", GIT_DEFAULTS, session)).toEqual([
      { text: "acme/web#4", href: "https://github.com/acme/web/issues/4" },
    ]);
  });

  it("links a GitHub Enterprise session through the GitHub rule on its own host", () => {
    const enterprise = repo("github", "https://ghe.example.com", "acme/app");
    expect(links("#3, acme/lib#4 and torvalds/linux#5", GIT_DEFAULTS, enterprise)).toEqual([
      { text: "#3", href: "https://ghe.example.com/acme/app/issues/3" },
      { text: "acme/lib#4", href: "https://ghe.example.com/acme/lib/issues/4" },
      { text: "torvalds/linux#5", href: "https://github.com/torvalds/linux/issues/5" },
    ]);
  });

  it("leaves bare numbers as text without a repository, but links GitHub's qualified form", () => {
    expect(links("#3, PR #4, !5 and acme/web#6", GIT_DEFAULTS, null)).toEqual([
      { text: "acme/web#6", href: "https://github.com/acme/web/issues/6" },
    ]);
  });

  it("sends a GitLab session's references outside its namespace to GitHub", () => {
    expect(
      links("facebook/react#7, acme/web#8 and other/lib!9", GIT_DEFAULTS, GITLAB_SESSION),
    ).toEqual([
      { text: "facebook/react#7", href: "https://github.com/facebook/react/issues/7" },
      { text: "acme/web#8", href: "https://gitlab.com/acme/web/-/issues/8" },
      // GitHub has no `!` marker, so the provider's own notation stays.
      { text: "other/lib!9", href: "https://gitlab.com/other/lib/-/merge_requests/9" },
    ]);
  });

  it("keeps every qualified reference on the session when GitHub is off", () => {
    const rules = [{ ...GITHUB_RULE, enabled: false }, GITLAB_RULE];
    expect(links("facebook/react#7", rules, GITLAB_SESSION)).toEqual([
      { text: "facebook/react#7", href: "https://gitlab.com/facebook/react/-/issues/7" },
    ]);
    expect(links("facebook/react#7", rules, null)).toEqual([]);
  });

  it("turns a session's host off with its disabled rule", () => {
    const rules = [GITHUB_RULE, { ...GITLAB_RULE, enabled: false }];
    expect(links("#3 and facebook/react#4", rules, GITLAB_SESSION)).toEqual([
      { text: "facebook/react#4", href: "https://github.com/facebook/react/issues/4" },
    ]);
  });
});

describe("sessionGitRule", () => {
  const ours = gitRule("Our GitLab", "gitlab", "gitlab.example.com");
  const rules = [...GIT_DEFAULTS, ours];

  it.each([
    ["github", "github.com", GITHUB_RULE],
    ["gitlab", "GitLab.com", GITLAB_RULE],
    ["gitlab", "gitlab.example.com:8443", ours],
    [null, "gitlab.example.com", ours],
    ["github", "ghe.example.com", GITHUB_RULE],
    [null, "ghe.example.com", null],
    ["bitbucket", "bitbucket.org", null],
    ["github", null, null],
  ] as const)("picks for %s on %s", (provider, host, expected) => {
    expect(sessionGitRule(rules, provider, host)).toBe(expected);
  });
});

describe("gitReferenceUrl", () => {
  const github: GitLinkTarget = {
    provider: "github",
    origin: "https://github.com",
    repository: "owner/repo",
    pullNumbers: new Set(),
  };

  it("builds each provider's issue and request pages", () => {
    const issue = { kind: "unspecified" as const, number: 7, repository: null };
    expect(gitReferenceUrl(github, issue)).toBe("https://github.com/owner/repo/issues/7");
    expect(gitReferenceUrl(github, { ...issue, kind: "request" })).toBe(
      "https://github.com/owner/repo/pull/7",
    );
    expect(gitReferenceUrl(github, { ...issue, repository: "a/b/c" })).toBeNull();
    const gitlab = { ...github, provider: "gitlab" as const, repository: "group/my project" };
    expect(gitReferenceUrl(gitlab, { ...issue, kind: "request" })).toBe(
      "https://github.com/group/my%20project/-/merge_requests/7",
    );
    const azure = { ...github, provider: "azure_devops" as const, repository: "org" };
    expect(gitReferenceUrl(azure, issue)).toBeNull();
  });
});

describe("remarkLinkRules with git references", () => {
  it("splits prose around links and leaves code and existing links alone", () => {
    const tree = {
      type: "root",
      children: [
        {
          type: "paragraph",
          children: [
            { type: "text", value: "Fixed #1 in " },
            { type: "inlineCode", value: "#2" },
            { type: "text", value: " (PR #3)." },
            { type: "link", url: "https://x.test", children: [{ type: "text", value: "#4" }] },
          ],
        },
        { type: "code", value: "#5" },
      ],
    };
    remarkLinkRules(compileLinkRules(GIT_DEFAULTS, GITHUB_SESSION))(tree);
    expect(tree.children[0].children).toEqual([
      { type: "text", value: "Fixed " },
      {
        type: "link",
        url: "https://github.com/acme/app/issues/1",
        title: "GitHub",
        children: [{ type: "text", value: "#1" }],
      },
      { type: "text", value: " in " },
      { type: "inlineCode", value: "#2" },
      { type: "text", value: " (" },
      {
        type: "link",
        url: "https://github.com/acme/app/pull/3",
        title: "GitHub",
        children: [{ type: "text", value: "PR #3" }],
      },
      { type: "text", value: ")." },
      { type: "link", url: "https://x.test", children: [{ type: "text", value: "#4" }] },
    ]);
    expect(tree.children[1]).toEqual({ type: "code", value: "#5" });
  });
});

describe("parseSessionReference", () => {
  it("reads the session and message ids", () => {
    expect(parseSessionReference("#omnigent-session-abc123/resp_1")).toEqual({
      sessionId: "abc123",
      messageId: "resp_1",
    });
    expect(parseSessionReference("#omnigent-session-abc123")).toEqual({
      sessionId: "abc123",
      messageId: null,
    });
  });

  it.each(["#omnigent-session-ab", "#omnigent-session-abc123/x?y", "#other-abc123"])(
    "rejects %s",
    (href) => {
      expect(parseSessionReference(href)).toBe(null);
    },
  );
});
