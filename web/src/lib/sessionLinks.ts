// Session links: the pages a session keeps coming back to, listed beside its
// open items. Both sources are read from the loaded transcript: links of a
// known kind that agent messages mention (SESSION_LINK_MATCHERS), and links
// pinned on purpose with a link label, `[L1] **Title** https://…`. A link label
// is an item label (itemLabels.ts), so it numbers, previews and closes like one.
// Links are named from the text written around them; nothing is fetched.

import {
  extractItemBlock,
  itemLabelTitle,
  proseLines,
  type ItemLabelEntry,
  type ItemLabelIndex,
  type ItemLabelSource,
} from "@/lib/itemLabels";
import { parseHttpUrl } from "@/lib/openLinkInApp";

/** A kind of link the Links list picks up by itself from agent messages. */
export interface SessionLinkMatcher {
  kind: string;
  /** What identifies the page `url` opens, however it is written; null for other links. */
  pageKey: (url: URL) => string | null;
  /** The title of a page no message has named. */
  untitled: (url: URL) => string;
}

const ARTIFACT_PATH_RE = /^\/(?:code\/)?artifact\/([^/]+)/;

// Pages published with Claude: claude.ai/artifact/<id> and claude.ai/code/artifact/<id>.
const artifactLinks: SessionLinkMatcher = {
  kind: "artifact",
  pageKey: (url) => {
    if (url.protocol !== "https:" || url.hostname !== "claude.ai") return null;
    const path = url.pathname.match(ARTIFACT_PATH_RE);
    return path ? `${url.origin}${path[0]}` : null;
  },
  untitled: (url) => `Artifact ${url.pathname.match(ARTIFACT_PATH_RE)?.[1].slice(0, 8) ?? ""}`,
};

/** In order: the first matcher that knows a link decides its kind. */
export const SESSION_LINK_MATCHERS: readonly SessionLinkMatcher[] = [artifactLinks];

const matcherFor = (url: URL) =>
  SESSION_LINK_MATCHERS.find((matcher) => matcher.pageKey(url) !== null);

/** Kind of a link pinned with a link label. */
export const PINNED_LINK_KIND = "pinned";

/** Whether `label` pins a link (`L1`, `L12`) rather than tracking an open item. */
export function isLinkItemLabel(label: string): boolean {
  return /^L\d{1,3}$/.test(label);
}

/** One row of the Links list. */
export interface SessionLink {
  /** The page's identity: one row per key. */
  key: string;
  href: string;
  title: string;
  /** The matcher's kind, or `PINNED_LINK_KIND`. */
  kind: string;
  /** A pinned link's label item, which previews and closes like any item. */
  item: ItemLabelEntry | null;
  /** The newest message that mentions the link. */
  lastMention: ItemLabelSource;
}

interface WrittenLink {
  url: URL;
  /** The text of a markdown link; null for a bare URL or one used as its own text. */
  text: string | null;
  /** A name the words around the link give it (see `nameAroundLink`); null when they don't. */
  context: string | null;
}

// A markdown link, an autolink, or a bare URL.
const LINK_SOURCE = String.raw`\[([^\]\n]*)\]\(\s*<?(https?:\/\/[^\s<>)]+)>?[^)\n]*\)|<(https?:\/\/[^\s<>]+)>|(https?:\/\/[^\s<>\x60"]+)`;

const withoutMarkup = (text: string) => text.replace(/\*\*|__|~~|`/g, "").trim();

/** Drops the sentence punctuation and closing markup a bare URL runs into. */
function trimBareUrl(raw: string): string {
  let url = raw;
  for (;;) {
    let next = url.replace(/[.,;:!?'*_~\]]+$/, "");
    const unbalanced = next.split(")").length > next.split("(").length;
    if (next.endsWith(")") && unbalanced) next = next.slice(0, -1);
    if (next === url) return url;
    url = next;
  }
}

const HEADING_TEXT_RE = /^ {0,3}#{1,6}\s+(.*?)\s*#*\s*$/;
const LIST_MARKER_RE = /^\s*(?:[-*+]\s+|\d{1,9}[.)]\s+|>\s*)*/;
const BOLD_SPAN_RE = /(\*\*|__)(?!\s)(.+?)\1/g;
const ONLY_BOLD_RE = /^(\*\*|__)(?!\s)(.+?)\1\s*:?$/;
// Words that lead up to a link without naming it: "The dashboard is at <url>".
const FILLER_WORDS_RE = /\s+(?:at|is|are|was|here|see|in|on|to|via|from|the|a|an)$/i;
const FRAGMENT_WORDS = 6;

/** Text with labels, link markup and emphasis removed, for a name. */
function nameText(text: string): string {
  return withoutMarkup(
    text
      .replace(new RegExp(LINK_SOURCE, "g"), (_match, linkText?: string) => linkText ?? "")
      .replace(/\[[A-Z]{1,3}\d{1,3}\]/g, ""),
  )
    .replace(/^[\s:.\-–—]+|[\s:.,;!?\-–—(]+$/g, "")
    .trim();
}

/** The heading text, or the whole bold span, a line holds; null when it holds neither. */
function headingOrBoldLine(line: string): string | null {
  const heading = line.match(HEADING_TEXT_RE);
  if (heading) return nameText(heading[1]) || null;
  const bold = line.replace(LIST_MARKER_RE, "").trim().match(ONLY_BOLD_RE);
  return bold ? nameText(bold[2]) || null : null;
}

/** The last few words of the sentence before a link, without filler or punctuation. */
function fragmentBefore(text: string): string | null {
  const sentence = nameText(
    text
      .replace(LIST_MARKER_RE, "")
      .split(/[.!?]\s+/)
      .pop() ?? "",
  );
  let fragment = sentence;
  for (let next = fragment.replace(FILLER_WORDS_RE, ""); next !== fragment;) {
    fragment = next;
    next = fragment.replace(FILLER_WORDS_RE, "");
  }
  const words = fragment
    .replace(/[\s:,;\-–—(]+$/, "")
    .split(/\s+/)
    .filter(Boolean);
  // One word ("Published <url>") says what happened, not what the page is.
  return words.length >= 2 ? words.slice(-FRAGMENT_WORDS).join(" ") : null;
}

/**
 * A name for a link from the words around it: a heading or bold title on its
 * line, else one on the line just before when the link starts its line, else
 * the end of the sentence leading up to it.
 */
function nameAroundLink(line: string, start: number, previous: string | null): string | null {
  const own = headingOrBoldLine(line);
  if (own) return own;
  const before = line.slice(0, start);
  const bold = [...before.matchAll(BOLD_SPAN_RE)].pop();
  if (bold) return nameText(bold[2]) || null;
  const titledAbove = previous === null ? null : headingOrBoldLine(previous);
  if (titledAbove && nameText(before.replace(LIST_MARKER_RE, "")) === "") return titledAbove;
  return fragmentBefore(before) ?? titledAbove;
}

/**
 * A short readable form of a URL for a link nothing names: the host and the
 * start of its path, never the whole address.
 */
export function shortLinkName(url: URL): string {
  const host = url.hostname.replace(/^www\./, "");
  const segments = url.pathname.split("/").filter(Boolean);
  const shown = segments
    .slice(0, 2)
    .map((segment) => (segment.length > 16 ? `${segment.slice(0, 12)}…` : segment));
  if (segments.length > 2) shown.push("…");
  return [host, ...shown].join("/");
}

/** The http(s) links `markdown` writes outside fenced code, in order. */
export function linksInMarkdown(markdown: string): WrittenLink[] {
  const links: WrittenLink[] = [];
  let previous: string | null = null;
  for (const line of proseLines(markdown)) {
    if (line === null) {
      previous = null;
      continue;
    }
    for (const match of line.matchAll(new RegExp(LINK_SOURCE, "g"))) {
      const url = parseHttpUrl(match[2] ?? match[3] ?? trimBareUrl(match[4]));
      if (!url) continue;
      const text = withoutMarkup(match[1] ?? "");
      links.push({
        url,
        text: text && !/^https?:\/\//i.test(text) ? text : null,
        context: nameAroundLink(line, match.index ?? 0, previous),
      });
    }
    previous = line.trim() === "" ? null : line;
  }
  return links;
}

interface LinkMention {
  key: string;
  kind: string;
  href: string;
  /** The link's own text. */
  title: string | null;
  /** A name from the words around it, used when no mention gives link text. */
  context: string | null;
  untitled: string;
}

// A finalized message keeps its source object across rebuilds, so each is read once.
const mentionsBySource = new WeakMap<ItemLabelSource, readonly LinkMention[]>();

function linkMentions(source: ItemLabelSource): readonly LinkMention[] {
  const cached = mentionsBySource.get(source);
  if (cached) return cached;
  const mentions = linksInMarkdown(source.text).flatMap(({ url, text, context }): LinkMention[] => {
    const matcher = matcherFor(url);
    const key = matcher?.pageKey(url);
    if (!matcher || !key) return [];
    return [
      {
        key,
        kind: matcher.kind,
        href: url.href,
        title: text,
        context,
        untitled: matcher.untitled(url),
      },
    ];
  });
  mentionsBySource.set(source, mentions);
  return mentions;
}

type Pin = Pick<SessionLink, "key" | "href" | "title">;

const pinsBySource = new WeakMap<ItemLabelSource, Map<string, Pin | null>>();

/** The link a link label pins: the first one in its defining block, titled like an item. */
function pinnedLink(item: ItemLabelEntry): Pin | null {
  const pins = pinsBySource.get(item.source) ?? new Map<string, Pin | null>();
  pinsBySource.set(item.source, pins);
  const cached = pins.get(item.label);
  if (cached !== undefined) return cached;
  const [link] = linksInMarkdown(extractItemBlock(item.source.text, item.label) ?? "");
  let pin: Pin | null = null;
  if (link) {
    const matcher = matcherFor(link.url);
    // An item without a bold title is titled by its first sentence, link included.
    const title = itemLabelTitle(item.source.text, item.label)
      .replace(new RegExp(LINK_SOURCE, "g"), (_match, text?: string) => text ?? "")
      .replace(/[\s:.\-–—]+$/, "");
    pin = {
      key: matcher?.pageKey(link.url) ?? link.url.href,
      href: link.url.href,
      title: title || link.text || matcher?.untitled(link.url) || shortLinkName(link.url),
    };
  }
  pins.set(item.label, pin);
  return pin;
}

/**
 * The Links list for a transcript's messages, in order. Pinned links come
 * first, as defined; then the pages agent messages mention, newest mention
 * first, each once. A page is titled by the newest link text given for it,
 * else the newest name the words around a mention give it, else its kind's
 * short name. A pin stands for its page, so closing the pin takes the page
 * off the list.
 */
export function collectSessionLinks(
  sources: Iterable<ItemLabelSource>,
  index: ItemLabelIndex | null,
): SessionLink[] {
  const mentioned = new Map<string, SessionLink>();
  const names = new Map<string, { text: string | null; context: string | null }>();
  for (const source of sources) {
    if (source.role !== "assistant") continue;
    for (const mention of linkMentions(source)) {
      const earlier = names.get(mention.key);
      const name = {
        text: mention.title ?? earlier?.text ?? null,
        context: mention.context ?? earlier?.context ?? null,
      };
      names.set(mention.key, name);
      // Re-inserting keeps the map in order of latest mention.
      mentioned.delete(mention.key);
      mentioned.set(mention.key, {
        key: mention.key,
        href: mention.href,
        title: name.text ?? name.context ?? mention.untitled,
        kind: mention.kind,
        item: null,
        lastMention: source,
      });
    }
  }
  const pinned: SessionLink[] = [];
  for (const item of index?.items.values() ?? []) {
    if (!isLinkItemLabel(item.label)) continue;
    const pin = pinnedLink(item);
    if (!pin) continue;
    mentioned.delete(pin.key);
    if (item.closedBy !== null) continue;
    pinned.push({ ...pin, kind: PINNED_LINK_KIND, item, lastMention: item.lastMention });
  }
  return [...pinned, ...[...mentioned.values()].reverse()];
}
