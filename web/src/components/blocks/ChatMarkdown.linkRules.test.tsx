// Link rules in chat markdown: references in plain text become links after
// item labels and file links have taken theirs, and text in links, code and
// code blocks is never rewritten.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ItemLabelIndexContext,
  ItemLabelMessageContext,
  ItemLabelSessionContext,
  buildItemLabelIndex,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import {
  compileLinkRules,
  type LinkRule,
  type LinkMatcher,
  LinkRuleMatchersContext,
  type SessionGitRepository,
} from "@/lib/linkRules";
import { FilePathAwareMessageResponse } from "./ChatMarkdown";

const JIRA: LinkRule = {
  name: "Jira",
  kind: "url",
  pattern: "BST-{num}",
  url: "https://jira.example.com/browse/BST-{num}",
  enabled: true,
};
const GITHUB_RULE: LinkRule = {
  name: "GitHub",
  kind: "git",
  provider: "github",
  host: "github.com",
  pattern: "",
  url: null,
  enabled: true,
};
const SESSION_RULE: LinkRule = {
  name: "Sessions",
  kind: "session",
  pattern: "",
  url: null,
  enabled: true,
};
const GITHUB: SessionGitRepository = {
  provider: "github",
  origin: "https://git.example.com",
  repository: "acme/app",
  pullNumbers: new Set(),
};

const DEFINING: ItemLabelSource = {
  messageId: "resp_1",
  role: "assistant",
  text: "[Q1] Should BST-1 ship? [Q2] Who reviews it?",
};

const INDEX = buildItemLabelIndex([{ source: DEFINING, labels: ["Q1", "Q2"], struck: [] }]);

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404 })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderMarkdown(
  markdown: string,
  rules: LinkRule[] = [JIRA],
  breaks = false,
  session: SessionGitRepository | null = GITHUB,
) {
  return render(
    markdownTree(markdown, compileLinkRules(rules, session), new QueryClient(), breaks),
  );
}

function markdownTree(
  markdown: string,
  matchers: readonly LinkMatcher[],
  client: QueryClient,
  breaks = false,
) {
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/c/current"]}>
        <ItemLabelSessionContext.Provider value="current">
          <ItemLabelIndexContext.Provider value={INDEX}>
            <ItemLabelMessageContext.Provider value="resp_2">
              <LinkRuleMatchersContext.Provider value={matchers}>
                <FilePathAwareMessageResponse breaks={breaks}>
                  {markdown}
                </FilePathAwareMessageResponse>
              </LinkRuleMatchersContext.Provider>
            </ItemLabelMessageContext.Provider>
          </ItemLabelIndexContext.Provider>
        </ItemLabelSessionContext.Provider>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function linkFor(text: string): HTMLAnchorElement | null {
  return (screen.queryByText(text, { selector: "a" }) as HTMLAnchorElement | null) ?? null;
}

describe("chat link rules", () => {
  it("links a reference in plain text with the rule's name as its title", async () => {
    renderMarkdown("Tracking BST-2135 here.");
    const link = await screen.findByText("BST-2135", { selector: "a" });
    expect(link.getAttribute("href")).toBe("https://jira.example.com/browse/BST-2135");
    expect(link.getAttribute("title")).toBe("Jira");
  });

  it("applies to user messages rendered with line breaks too", async () => {
    renderMarkdown("first line\nBST-7", [JIRA], true);
    expect((await screen.findByText("BST-7", { selector: "a" })).getAttribute("href")).toBe(
      "https://jira.example.com/browse/BST-7",
    );
  });

  it("leaves inline code, code blocks and existing links alone", async () => {
    renderMarkdown(
      [
        "Inline `BST-1` code.",
        "",
        "```",
        "BST-2 in a block",
        "```",
        "",
        "[BST-3 link](https://example.com/other) and BST-4.",
      ].join("\n"),
    );
    await screen.findByText("BST-4", { selector: "a" });
    expect(screen.getByText("BST-1").tagName).toBe("CODE");
    expect(linkFor("BST-1")).toBe(null);
    expect(screen.getByText(/BST-2 in a block/).closest("a")).toBe(null);
    expect(screen.getByText("BST-3 link").getAttribute("href")).toBe("https://example.com/other");
  });

  it("runs after item labels and file links", async () => {
    renderMarkdown("[Q1] covers BST-5 and [notes](docs/BST-6.md).");
    await screen.findByText("BST-5", { selector: "a" });
    // The label is still a chip, not a rule link.
    expect(screen.getByRole("button", { name: /Q1/ })).toBeTruthy();
    // The file link keeps its path; the rule doesn't relink its text.
    expect(linkFor("BST-6")).toBe(null);
  });

  it("encodes what a hostile message puts in a capture", async () => {
    const rule: LinkRule = {
      name: "Any",
      kind: "url",
      pattern: "/T:([^ ]{1,30})/",
      url: "https://e.example/q?x={1}",
      enabled: true,
    };
    renderMarkdown('T:"onmouseover=alert(1)', [rule]);
    const link = await screen.findByText('T:"onmouseover=alert(1)', { selector: "a" });
    expect(link.getAttribute("href")).toBe("https://e.example/q?x=%22onmouseover%3Dalert(1)");
    expect(link.getAttribute("onmouseover")).toBe(null);
  });

  it("links GitHub references on the session's repository host", async () => {
    renderMarkdown("Fixes #12.", [GITHUB_RULE]);
    expect((await screen.findByText("#12", { selector: "a" })).getAttribute("href")).toBe(
      "https://git.example.com/acme/app/issues/12",
    );
  });

  it("links issue and pull request references except inside code", async () => {
    renderMarkdown(
      [
        "Reported in #12, fixed by PR #34 and backported in other/project#56.",
        "The span `#78` and the block below stay plain:",
        "",
        "```sh",
        "gh pr checkout 34  # not a reference: #34",
        "```",
      ].join("\n"),
      [GITHUB_RULE],
    );
    expect(linkFor("#12")?.getAttribute("href")).toBe("https://git.example.com/acme/app/issues/12");
    expect((await screen.findByText("PR #34", { selector: "a" })).getAttribute("href")).toBe(
      "https://git.example.com/acme/app/pull/34",
    );
    // Another owner's repository is GitHub's, not the Enterprise host's.
    expect(linkFor("other/project#56")?.getAttribute("href")).toBe(
      "https://github.com/other/project/issues/56",
    );
    expect(screen.getByText("#78").tagName).toBe("CODE");
  });

  it("leaves bare references as text when the session has no repository", async () => {
    renderMarkdown("Reported in #12, fixed by PR #34 in acme/web#5.", [GITHUB_RULE], false, null);
    expect((await screen.findByText("acme/web#5", { selector: "a" })).getAttribute("href")).toBe(
      "https://github.com/acme/web/issues/5",
    );
    expect(linkFor("#12")).toBe(null);
    expect(linkFor("PR #34")).toBe(null);
  });

  it("re-renders a message when its rules arrive after it rendered", async () => {
    const client = new QueryClient();
    const view = render(markdownTree("Fixes #12.", [], client));
    await screen.findByText(/Fixes #12/);
    expect(linkFor("#12")).toBe(null);
    view.rerender(markdownTree("Fixes #12.", compileLinkRules([GITHUB_RULE], GITHUB), client));
    expect((await screen.findByText("#12", { selector: "a" })).getAttribute("href")).toBe(
      "https://git.example.com/acme/app/issues/12",
    );
  });

  it("opens a session reference in the app at the message", async () => {
    renderMarkdown("See session:abc123def/resp_9 for context.", [SESSION_RULE]);
    const link = await screen.findByText("session:abc123def/resp_9", { selector: "a" });
    expect(link.getAttribute("href")).toBe("/c/abc123def?message=resp_9");
    fireEvent.click(link);
    expect(screen.getByTestId("location").textContent).toBe("/c/abc123def?message=resp_9");
  });

  it("keeps a hand-written session href as text where no rules apply", async () => {
    const { container } = render(
      <MemoryRouter>
        <FilePathAwareMessageResponse>
          {"[forged](#omnigent-session-abc123def) and BST-8"}
        </FilePathAwareMessageResponse>
      </MemoryRouter>,
    );
    await screen.findByText(/and BST-8/);
    expect(container.querySelector("a")).toBe(null);
  });
});
