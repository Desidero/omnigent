import { describe, expect, it } from "vitest";
import {
  compileLinkPattern,
  compileLinkRules,
  findLinks,
  type GithubLinkTarget,
  type LinkRule,
  linkRuleError,
  linkRuleErrors,
  parseSessionReference,
} from "./linkRules";

function urlRule(pattern: string, url: string, name = "Rule"): LinkRule {
  return { name, kind: "url", pattern, url, enabled: true };
}

const GITHUB: GithubLinkTarget = {
  origin: "https://git.example.com",
  repo: "acme/app",
  pullNumbers: new Set([7]),
};

function links(text: string, rules: LinkRule[], github: GithubLinkTarget | null = null) {
  return findLinks(text, compileLinkRules(rules, github)).map(({ start, end, href }) => ({
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
    expect(
      linkRuleError({ name: "GH", kind: "github", pattern: "#{num}", url: null, enabled: true }),
    ).toContain("takes no pattern");
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

  it("links GitHub references on the session's own host", () => {
    const github: LinkRule = { name: "GH", kind: "github", pattern: "", url: null, enabled: true };
    expect(links("Fixes #12, see #7 and other/lib#3. a#4", [github], GITHUB)).toEqual([
      { text: "#12", href: "https://git.example.com/acme/app/issues/12" },
      { text: "#7", href: "https://git.example.com/acme/app/pull/7" },
      { text: "other/lib#3", href: "https://git.example.com/other/lib/issues/3" },
    ]);
    expect(links("#12", [github], null)).toEqual([]);
  });

  it("turns session references into in-app hrefs", () => {
    const session: LinkRule = { name: "S", kind: "session", pattern: "", url: null, enabled: true };
    expect(links("see session:abc123def and session:abc123def/resp_9", [session])).toEqual([
      { text: "session:abc123def", href: "#omnigent-session-abc123def" },
      { text: "session:abc123def/resp_9", href: "#omnigent-session-abc123def/resp_9" },
    ]);
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
