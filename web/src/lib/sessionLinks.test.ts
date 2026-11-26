import { describe, expect, it } from "vitest";
import {
  buildItemLabelIndex,
  itemLabelsIn,
  struckItemLabelsIn,
  type ItemLabelIndex,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import {
  PINNED_LINK_KIND,
  collectSessionLinks,
  isLinkItemLabel,
  linksInMarkdown,
  shortLinkName,
} from "./sessionLinks";

type Message = string | { user: string };

function sourcesOf(...messages: Message[]): ItemLabelSource[] {
  return messages.map((message, position) =>
    typeof message === "string"
      ? { messageId: `m${position}`, role: "assistant", text: message }
      : { messageId: `m${position}`, role: "user", text: message.user },
  );
}

function indexOf(sources: ItemLabelSource[]): ItemLabelIndex {
  return buildItemLabelIndex(
    sources.map((source) => ({
      source,
      labels: itemLabelsIn(source.text),
      struck: struckItemLabelsIn(source.text),
    })),
  );
}

function linksOf(...messages: Message[]) {
  const sources = sourcesOf(...messages);
  return collectSessionLinks(sources, indexOf(sources));
}

const titles = (...messages: Message[]) => linksOf(...messages).map((link) => link.title);

describe("linksInMarkdown", () => {
  it("reads markdown links, autolinks and bare URLs, without the punctuation around them", () => {
    const links = linksInMarkdown(
      [
        "See [the **board**](https://example.com/board) and <https://example.com/auto>.",
        "Also (https://example.com/wiki/Page_(draft)), **https://example.com/bold**.",
      ].join("\n"),
    );
    expect(links.map((link) => [link.url.href, link.text])).toEqual([
      ["https://example.com/board", "the board"],
      ["https://example.com/auto", null],
      ["https://example.com/wiki/Page_(draft)", null],
      ["https://example.com/bold", null],
    ]);
  });

  it("skips fenced code but not inline code, and treats a URL used as link text as untitled", () => {
    const links = linksInMarkdown(
      [
        "```",
        "https://example.com/in-a-fence",
        "```",
        "Open `https://example.com/inline` or [https://example.com/self](https://example.com/self).",
        "Not a link: ftp://example.com/file",
      ].join("\n"),
    );
    expect(links.map((link) => [link.url.href, link.text])).toEqual([
      ["https://example.com/inline", null],
      ["https://example.com/self", null],
    ]);
  });
});

describe("collectSessionLinks: pages agent messages mention", () => {
  it("collects artifact links from agent messages only, and no other link", () => {
    const links = linksOf(
      "Published the [Patch catalog](https://claude.ai/artifact/1f3a9c20-aaaa) from https://github.com/acme/app/pull/7.",
      { user: "Is https://claude.ai/artifact/user-pasted the same page?" },
      "The review page is at https://claude.ai/code/artifact/77aa88bb-cccc.",
    );
    expect(links.map(({ title, href, kind, item }) => ({ title, href, kind, item }))).toEqual([
      {
        title: "The review page",
        href: "https://claude.ai/code/artifact/77aa88bb-cccc",
        kind: "artifact",
        item: null,
      },
      {
        title: "Patch catalog",
        href: "https://claude.ai/artifact/1f3a9c20-aaaa",
        kind: "artifact",
        item: null,
      },
    ]);
  });

  it("lists a page once, newest mention first, titled by the newest link text given", () => {
    const links = linksOf(
      "Made the [catalog](https://claude.ai/artifact/aaa) and the [board](https://claude.ai/artifact/bbb).",
      "Renamed: [Patch catalog](https://claude.ai/artifact/aaa?v=2#top).",
      "Updated https://claude.ai/artifact/aaa again.",
    );
    expect(links.map((link) => [link.title, link.href, link.lastMention.messageId])).toEqual([
      ["Patch catalog", "https://claude.ai/artifact/aaa", "m2"],
      ["board", "https://claude.ai/artifact/bbb", "m0"],
    ]);
  });

  it("names a link from a heading or bold title on its line or just above, else the words before it", () => {
    expect(
      titles(
        "## Release report https://claude.ai/artifact/aaa",
        "**Patch catalog**\nhttps://claude.ai/artifact/bbb",
        "- **Board:** https://claude.ai/artifact/ccc",
        "Done. The dashboard for the cache rollout numbers is at https://claude.ai/artifact/ddd.",
        "Published https://claude.ai/artifact/eee",
      ),
    ).toEqual([
      "Artifact eee",
      "dashboard for the cache rollout numbers",
      "Board",
      "Patch catalog",
      "Release report",
    ]);
  });

  it("keeps link text over a name from the words around a later mention", () => {
    expect(
      titles(
        "Made the [catalog](https://claude.ai/artifact/aaa).",
        "The patch list is https://claude.ai/artifact/aaa",
      ),
    ).toEqual(["catalog"]);
    expect(
      titles(
        "The patch list is https://claude.ai/artifact/aaa",
        "Updated https://claude.ai/artifact/aaa again.",
      ),
    ).toEqual(["The patch list"]);
  });

  it("ignores look-alike hosts, other claude.ai pages and plain http", () => {
    expect(
      linksOf(
        "https://claude.ai.example.com/artifact/aaa https://claude.ai/chat/aaa http://claude.ai/artifact/aaa https://claude.ai/artifact/",
      ),
    ).toEqual([]);
  });
});

describe("collectSessionLinks: links pinned with a link label", () => {
  it("recognizes link labels by their letter", () => {
    expect(["L1", "L12", "L999"].every(isLinkItemLabel)).toBe(true);
    expect(["Q1", "LL1", "L", "FL2"].some(isLinkItemLabel)).toBe(false);
  });

  it("pins the link in the label's own block, titled by its bold title, ahead of mentioned pages", () => {
    const links = linksOf(
      "Published https://claude.ai/artifact/aaa.",
      "- [L1] **Release checklist** https://example.com/checklist\n- [L2] **Runbook:** [open it](https://example.com/runbook) (see also https://example.com/other)",
    );
    expect(links.map(({ title, href, kind }) => [title, href, kind])).toEqual([
      ["Release checklist", "https://example.com/checklist", PINNED_LINK_KIND],
      ["Runbook", "https://example.com/runbook", PINNED_LINK_KIND],
      ["Artifact aaa", "https://claude.ai/artifact/aaa", "artifact"],
    ]);
    expect(links[0].item?.label).toBe("L1");
  });

  it("falls back to the first sentence, the link text, then a short form of the URL for a title", () => {
    expect(
      titles(
        "[L1] Staging dashboard: https://example.com/a\n\n[L2] [Design notes](https://example.com/b)\n\n[L3] https://docs.example.com/c",
      ),
    ).toEqual(["Staging dashboard", "Design notes", "docs.example.com/c"]);
  });

  it("shortens a URL to its host and the start of its path", () => {
    expect(shortLinkName(new URL("https://www.example.com/"))).toBe("example.com");
    expect(
      shortLinkName(new URL("https://docs.example.com/d/1AbCdEfGhIjKlMnOpQrStUv/edit?usp=sharing")),
    ).toBe("docs.example.com/d/1AbCdEfGhIjK…/…");
  });

  it("pins from a single message and from the user, but not a label without a link", () => {
    expect(titles("[L1] **Release checklist** https://example.com/checklist")).toEqual([
      "Release checklist",
    ]);
    expect(titles({ user: "[L1] **My notes** https://example.com/notes" })).toEqual(["My notes"]);
    expect(titles("[L1] **Release checklist** is coming.", "[Q1] **Ship it?**")).toEqual([]);
  });

  it("drops a pinned link once its label is struck through, and restores it on a plain mention", () => {
    const pinned = "[L1] **Release checklist** https://example.com/checklist";
    expect(titles(pinned, "~~[L1]~~ replaced by the tracker.")).toEqual([]);
    expect(titles(pinned, "~~[L1]~~ replaced.", "Back to [L1] after all.")).toEqual([
      "Release checklist",
    ]);
  });

  it("lets a pin stand for a mentioned page, so closing the pin takes the page off the list", () => {
    const published = "Published the [catalog](https://claude.ai/artifact/aaa).";
    const pinned = "[L1] **Patch catalog** https://claude.ai/artifact/aaa?v=2";
    expect(titles(published, pinned)).toEqual(["Patch catalog"]);
    expect(titles(published, pinned, "~~[L1]~~ unpublished it.")).toEqual([]);
  });
});
