// Chat link rules: short references such as `BST-2135`, `#123` or
// `session:<id>` that chat messages render as links. The server validates a
// rule when it is saved (omnigent/link_rules.py); this module checks it again
// before compiling, with the same rules, because every viewer's browser runs
// the result on every message. See docs/chat-link-rules.md.
//
// Compiled regexes avoid lookbehind and named groups, which older Safari can't
// parse: a match's leading boundary is consumed as group 1 instead.

import { createContext } from "react";

export type LinkRuleKind = "url" | "github" | "session";

export interface LinkRule {
  name: string;
  kind: LinkRuleKind;
  /** `url` kind: a short form (`BST-{num}`) or a raw `/regex/`; `""` otherwise. */
  pattern: string;
  /** `url` kind: the http(s) template, e.g. `https://jira.example.com/browse/BST-{num}`. */
  url: string | null;
  enabled: boolean;
}

export const MAX_LINK_RULES = 32;
export const MAX_LINK_RULE_NAME_LENGTH = 64;
export const MAX_LINK_PATTERN_LENGTH = 200;
export const MAX_LINK_URL_LENGTH = 500;
const MAX_REPEAT = 64;
const MAX_REPEATS = 3;
const MAX_GROUPS = 9;

/** Short-form placeholders and the text each one matches. */
export const SHORT_FORM_PLACEHOLDERS: Record<string, string> = {
  num: String.raw`\d{1,10}`,
  key: "[A-Z][A-Z0-9]{1,9}",
  id: "[A-Za-z0-9_-]{1,64}",
};

const LEADING_BOUNDARY = "(^|[^A-Za-z0-9_])";
const TRAILING_BOUNDARY = "(?![A-Za-z0-9_])";
const SHORT_FORM_TOKEN = /\{([a-z]+)\}/g;
const URL_PLACEHOLDER = /\{([a-z]+|\d)\}/g;
const URL_FIXED_PREFIX = /^https?:\/\/[^/?#{}\s@\\]+[/?#]/i;
const CLASS_ESCAPES = new Set(["d", "D", "w", "W", "s", "S"]);
const ALPHANUMERIC = /^[A-Za-z0-9]$/;

/** Fragment href a session reference carries from the remark pass to the link renderer. */
export const SESSION_REFERENCE_HREF_PREFIX = "#omnigent-session-";

export class LinkRuleError extends Error {}

interface CompiledPattern {
  source: string;
  groupNames: string[];
  groupCount: number;
}

/**
 * Compile a `url` rule's pattern after checking it is safe to run.
 *
 * @throws LinkRuleError naming the problem.
 */
export function compileLinkPattern(pattern: string): CompiledPattern {
  if (!pattern) throw new LinkRuleError("pattern: required for a url rule");
  if (pattern.length > MAX_LINK_PATTERN_LENGTH) {
    throw new LinkRuleError(`pattern: longer than ${MAX_LINK_PATTERN_LENGTH} characters`);
  }
  const compiled =
    pattern.length >= 2 && pattern.startsWith("/") && pattern.endsWith("/")
      ? checkRegex(pattern.slice(1, -1))
      : compileShortForm(pattern);
  let regex: RegExp;
  try {
    regex = new RegExp(`^(?:${compiled.source})$`);
  } catch (error) {
    throw new LinkRuleError(`pattern: ${(error as Error).message}`);
  }
  if (regex.test("")) throw new LinkRuleError("pattern: must not match empty text");
  return compiled;
}

function escapeRegex(text: string): string {
  return text.replace(/[\\^$.*+?()[\]{}|/-]/g, "\\$&");
}

function compileShortForm(pattern: string): CompiledPattern {
  if (/\s/.test(pattern)) throw new LinkRuleError("pattern: a short form can't contain spaces");
  const parts: string[] = [];
  const groupNames: string[] = [];
  let last = 0;
  for (const match of pattern.matchAll(SHORT_FORM_TOKEN)) {
    const literal = pattern.slice(last, match.index);
    if (/[{}]/.test(literal))
      throw new LinkRuleError("pattern: unmatched { or } in the short form");
    parts.push(escapeRegex(literal));
    const name = match[1];
    const placeholder = SHORT_FORM_PLACEHOLDERS[name];
    if (placeholder === undefined) {
      const known = Object.keys(SHORT_FORM_PLACEHOLDERS)
        .map((key) => `{${key}}`)
        .join(", ");
      throw new LinkRuleError(`pattern: unknown placeholder {${name}}; use ${known}`);
    }
    parts.push(`(${placeholder})`);
    groupNames.push(name);
    last = (match.index ?? 0) + match[0].length;
  }
  const tail = pattern.slice(last);
  if (/[{}]/.test(tail)) throw new LinkRuleError("pattern: unmatched { or } in the short form");
  parts.push(escapeRegex(tail));
  if (groupNames.length === 0) {
    throw new LinkRuleError("pattern: a short form needs a placeholder such as {num}");
  }
  if (groupNames.length > MAX_REPEATS + 1) {
    throw new LinkRuleError(`pattern: at most ${MAX_REPEATS + 1} placeholders`);
  }
  return { source: parts.join(""), groupNames, groupCount: groupNames.length };
}

interface GroupState {
  hasRepeat: boolean;
  hasAlternation: boolean;
}

/** Check a raw regex against the shared safe subset and cap its repeats. */
function checkRegex(body: string): CompiledPattern {
  const out: string[] = [];
  const stack: GroupState[] = [{ hasRepeat: false, hasAlternation: false }];
  // What a quantifier would apply to: nothing, an atom, or a closed group.
  let last: GroupState | "atom" | null = null;
  let groups = 0;
  let repeats = 0;
  let index = 0;
  while (index < body.length) {
    const char = body[index];
    if (char === "\\") {
      if (index + 1 >= body.length) throw new LinkRuleError("pattern: ends with a lone backslash");
      const escaped = body[index + 1];
      if (escaped === "b" || escaped === "B") last = null;
      else if (CLASS_ESCAPES.has(escaped) || !ALPHANUMERIC.test(escaped)) last = "atom";
      else {
        throw new LinkRuleError(
          `pattern: \\${escaped} isn't supported (no backreferences or letter escapes other than \\d \\w \\s \\b and their capitals)`,
        );
      }
      out.push(body.slice(index, index + 2));
      index += 2;
    } else if (char === "[") {
      const end = classEnd(body, index);
      out.push(body.slice(index, end + 1));
      last = "atom";
      index = end + 1;
    } else if (char === "(") {
      if (body.startsWith("(?", index)) {
        if (!body.startsWith("(?:", index)) {
          throw new LinkRuleError(
            "pattern: only (?: ) groups are supported; no lookaround, named groups or inline flags",
          );
        }
        out.push("(?:");
        index += 3;
      } else {
        groups += 1;
        out.push("(");
        index += 1;
      }
      stack.push({ hasRepeat: false, hasAlternation: false });
      last = null;
    } else if (char === ")") {
      if (stack.length === 1) throw new LinkRuleError("pattern: unbalanced )");
      const closed = stack.pop()!;
      const parent = stack[stack.length - 1];
      parent.hasRepeat ||= closed.hasRepeat;
      parent.hasAlternation ||= closed.hasAlternation;
      out.push(")");
      last = closed;
      index += 1;
    } else if (char === "|") {
      stack[stack.length - 1].hasAlternation = true;
      out.push("|");
      last = null;
      index += 1;
    } else if (char === "*" || char === "+" || char === "?" || char === "{") {
      const quantifier = readQuantifier(body, index);
      if (quantifier === null)
        throw new LinkRuleError("pattern: escape a literal { or } as \\{ or \\}");
      const { text, low, high, end } = quantifier;
      if (last === null) throw new LinkRuleError(`pattern: nothing to repeat before ${text}`);
      if (high === null || high > 1) {
        if (last !== "atom" && (last.hasRepeat || last.hasAlternation)) {
          throw new LinkRuleError("pattern: a repeated group can't contain another repeat or |");
        }
        repeats += 1;
        if (repeats > MAX_REPEATS)
          throw new LinkRuleError(`pattern: at most ${MAX_REPEATS} repeats`);
      }
      if ((high !== null && high > MAX_REPEAT) || low > MAX_REPEAT) {
        throw new LinkRuleError(`pattern: repeat counts are capped at ${MAX_REPEAT}`);
      }
      stack[stack.length - 1].hasRepeat = true;
      out.push(high === null ? `{${low},${MAX_REPEAT}}` : text);
      index = end;
      if (body[index] === "?") {
        out.push("?");
        index += 1;
      }
      last = null;
    } else if (char === "}") {
      throw new LinkRuleError("pattern: escape a literal { or } as \\{ or \\}");
    } else if (char === "^" || char === "$") {
      out.push(char);
      last = null;
      index += 1;
    } else {
      out.push(char);
      last = "atom";
      index += 1;
    }
  }
  if (stack.length !== 1) throw new LinkRuleError("pattern: unbalanced (");
  if (groups > MAX_GROUPS) throw new LinkRuleError(`pattern: at most ${MAX_GROUPS} capture groups`);
  return { source: out.join(""), groupNames: [], groupCount: groups };
}

function classEnd(body: string, start: number): number {
  let index = start + 1;
  if (body[index] === "^") index += 1;
  // Python reads []] as a class holding ], a browser as an empty class.
  if (body[index] === "]") {
    throw new LinkRuleError("pattern: escape ] at the start of a [ ] class as \\]");
  }
  while (index < body.length) {
    const char = body[index];
    if (char === "\\") {
      const escaped = body[index + 1] ?? "";
      if (!escaped || (ALPHANUMERIC.test(escaped) && !CLASS_ESCAPES.has(escaped))) {
        throw new LinkRuleError(`pattern: \\${escaped} isn't supported inside [ ]`);
      }
      index += 2;
      continue;
    }
    if (char === "[") throw new LinkRuleError("pattern: escape [ inside a [ ] class as \\[");
    if (char === "]") return index;
    index += 1;
  }
  throw new LinkRuleError("pattern: unclosed [");
}

function readQuantifier(
  body: string,
  start: number,
): { text: string; low: number; high: number | null; end: number } | null {
  const char = body[start];
  if (char === "*") return { text: "*", low: 0, high: null, end: start + 1 };
  if (char === "+") return { text: "+", low: 1, high: null, end: start + 1 };
  if (char === "?") return { text: "?", low: 0, high: 1, end: start + 1 };
  const match = /^\{(\d{1,4})(,(\d{0,4}))?\}/.exec(body.slice(start));
  if (!match) return null;
  const low = Number(match[1]);
  const high = match[2] === undefined ? low : match[3] ? Number(match[3]) : null;
  if (high !== null && high < low) {
    throw new LinkRuleError("pattern: a {min,max} repeat needs min <= max");
  }
  return { text: match[0], low, high, end: start + match[0].length };
}

/**
 * Check that a URL template always yields an http(s) link whose scheme and
 * host no match can change.
 *
 * @throws LinkRuleError naming the problem.
 */
export function checkUrlTemplate(template: string, compiled: CompiledPattern): void {
  if (!template) throw new LinkRuleError("url: required for a url rule");
  if (template.length > MAX_LINK_URL_LENGTH) {
    throw new LinkRuleError(`url: longer than ${MAX_LINK_URL_LENGTH} characters`);
  }
  // oxlint-disable-next-line no-control-regex -- rejecting control characters is the point
  if (/[\s\u0000-\u001f\u007f]/.test(template)) {
    throw new LinkRuleError("url: can't contain spaces or control characters");
  }
  const first = template.indexOf("{");
  const prefix = first >= 0 ? template.slice(0, first) : `${template}/`;
  if (!URL_FIXED_PREFIX.test(prefix)) {
    throw new LinkRuleError(
      "url: must start with https:// or http:// and a host, followed by / ? or # before any placeholder",
    );
  }
  for (const match of template.matchAll(URL_PLACEHOLDER)) {
    const token = match[1];
    if (/^\d$/.test(token)) {
      if (Number(token) > compiled.groupCount) {
        throw new LinkRuleError(
          `url: {${token}} has no matching group in the pattern (${compiled.groupCount} group(s))`,
        );
      }
    } else if (!compiled.groupNames.includes(token)) {
      const available = compiled.groupNames.map((name) => `{${name}}`).join(", ") || "{0}, {1}…";
      throw new LinkRuleError(`url: unknown placeholder {${token}}; use ${available}`);
    }
  }
  if (/[{}]/.test(template.replace(URL_PLACEHOLDER, ""))) {
    throw new LinkRuleError("url: unmatched { or }");
  }
}

/** Why `rule` can't be used, or `null` when it is valid on its own. */
export function linkRuleError(rule: LinkRule): string | null {
  const name = rule.name.trim();
  if (!name) return "name: required";
  if (name.length > MAX_LINK_RULE_NAME_LENGTH) {
    return `name: longer than ${MAX_LINK_RULE_NAME_LENGTH} characters`;
  }
  try {
    if (rule.kind === "url") checkUrlTemplate(rule.url ?? "", compileLinkPattern(rule.pattern));
    else if (rule.pattern || rule.url)
      return `the built-in ${rule.kind} kind takes no pattern or url`;
  } catch (error) {
    if (error instanceof LinkRuleError) return error.message;
    throw error;
  }
  return null;
}

/**
 * Per-rule errors for a whole list, including repeated names and a built-in
 * kind listed twice; `null` where a rule is fine.
 */
export function linkRuleErrors(rules: readonly LinkRule[]): (string | null)[] {
  const names = new Map<string, number>();
  const builtins = new Map<LinkRuleKind, number>();
  return rules.map((rule, index) => {
    const own = linkRuleError(rule);
    if (own) return own;
    const folded = rule.name.trim().toLowerCase();
    if (names.has(folded)) return `two rules are named ${rule.name.trim()}`;
    names.set(folded, index);
    if (rule.kind !== "url") {
      if (builtins.has(rule.kind)) return `only one ${rule.kind} rule`;
      builtins.set(rule.kind, index);
    }
    return null;
  });
}

/** Where `#123` and `owner/repo#123` link: the session's repository on its provider's host. */
export interface GithubLinkTarget {
  /** Scheme and host, e.g. `https://github.example.com`. */
  origin: string;
  /** `owner/repo` of the session's repository. */
  repo: string;
  /** Pull request numbers known on `repo`; other numbers link as issues. */
  pullNumbers: ReadonlySet<number>;
}

/** One compiled rule: a global regex and how to turn its match into an href. */
export interface LinkMatcher {
  name: string;
  regex: RegExp;
  href: (match: RegExpExecArray) => string | null;
}

const GITHUB_QUALIFIED = String.raw`([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})#(\d{1,10})`;
const GITHUB_LOCAL = String.raw`#(\d{1,10})`;
const SESSION_REFERENCE = String.raw`session:([A-Za-z0-9_-]{6,64})(?:/([A-Za-z0-9_-]{1,128}))?`;

function bounded(source: string): RegExp {
  return new RegExp(`${LEADING_BOUNDARY}(?:${source})${TRAILING_BOUNDARY}`, "g");
}

function safeHttpUrl(href: string): string | null {
  try {
    const url = new URL(href);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function githubHref(target: GithubLinkTarget, repo: string, number: string): string | null {
  const [owner, name] = repo.split("/");
  const sameRepo = repo.toLowerCase() === target.repo.toLowerCase();
  // GitHub redirects /issues/N to the pull request when N is one.
  const section = sameRepo && target.pullNumbers.has(Number(number)) ? "pull" : "issues";
  return safeHttpUrl(
    `${target.origin}/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/${section}/${number}`,
  );
}

/**
 * Compile the enabled rules into matchers, skipping any that fail the checks.
 *
 * @param rules - The user's rules, in priority order.
 * @param github - The session's repository, or `null` when it has none, which
 *   leaves GitHub references as text.
 */
export function compileLinkRules(
  rules: readonly LinkRule[],
  github: GithubLinkTarget | null,
): LinkMatcher[] {
  const errors = linkRuleErrors(rules);
  const matchers: LinkMatcher[] = [];
  rules.forEach((rule, index) => {
    if (!rule.enabled || errors[index] !== null) return;
    if (rule.kind === "github") {
      if (github === null) return;
      matchers.push(
        {
          name: rule.name,
          regex: bounded(GITHUB_QUALIFIED),
          href: (match) => githubHref(github, `${match[2]}/${match[3]}`, match[4]),
        },
        {
          name: rule.name,
          regex: bounded(GITHUB_LOCAL),
          href: (match) => githubHref(github, github.repo, match[2]),
        },
      );
    } else if (rule.kind === "session") {
      matchers.push({
        name: rule.name,
        regex: bounded(SESSION_REFERENCE),
        href: (match) =>
          `${SESSION_REFERENCE_HREF_PREFIX}${match[2]}${match[3] ? `/${match[3]}` : ""}`,
      });
    } else {
      const compiled = compileLinkPattern(rule.pattern);
      const template = rule.url ?? "";
      matchers.push({
        name: rule.name,
        regex: bounded(compiled.source),
        href: (match) => {
          const whole = match[0].slice(match[1].length);
          const value = (token: string) => {
            if (/^\d$/.test(token)) return token === "0" ? whole : (match[Number(token) + 1] ?? "");
            return match[compiled.groupNames.indexOf(token) + 2] ?? "";
          };
          return safeHttpUrl(
            template.replace(URL_PLACEHOLDER, (_text, token: string) =>
              encodeURIComponent(value(token)),
            ),
          );
        },
      });
    }
  });
  return matchers;
}

/** A link found in text: `[start, end)` and where it goes. */
export interface LinkSpan {
  start: number;
  end: number;
  href: string;
  name: string;
}

/**
 * Find the links in `text`. Overlaps go to the earliest match, then to the
 * rule listed first.
 */
export function findLinks(text: string, matchers: readonly LinkMatcher[]): LinkSpan[] {
  const found: (LinkSpan & { order: number })[] = [];
  matchers.forEach((matcher, order) => {
    matcher.regex.lastIndex = 0;
    for (let match = matcher.regex.exec(text); match; match = matcher.regex.exec(text)) {
      const start = match.index + match[1].length;
      const end = match.index + match[0].length;
      if (end === match.index) matcher.regex.lastIndex += 1;
      if (end <= start) continue;
      const href = matcher.href(match);
      if (href) found.push({ start, end, href, name: matcher.name, order });
    }
  });
  found.sort((a, b) => a.start - b.start || a.order - b.order);
  const spans: LinkSpan[] = [];
  let reached = 0;
  for (const { order: _order, ...span } of found) {
    if (span.start < reached) continue;
    spans.push(span);
    reached = span.end;
  }
  return spans;
}

interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  title?: string | null;
  children?: MdastNode[];
}

// Text under these nodes is already a link (including item-label chips and
// file links), code, or raw markup, so no rule rewrites it.
const SKIPPED_PARENTS = new Set([
  "link",
  "linkReference",
  "definition",
  "inlineCode",
  "code",
  "html",
]);

function splitText(node: MdastNode, matchers: readonly LinkMatcher[]): MdastNode[] {
  const text = node.value ?? "";
  const spans = findLinks(text, matchers);
  if (spans.length === 0) return [node];
  const parts: MdastNode[] = [];
  let last = 0;
  for (const span of spans) {
    if (span.start > last) parts.push({ type: "text", value: text.slice(last, span.start) });
    parts.push({
      type: "link",
      url: span.href,
      title: span.name,
      children: [{ type: "text", value: text.slice(span.start, span.end) }],
    });
    last = span.end;
  }
  if (last < text.length) parts.push({ type: "text", value: text.slice(last) });
  return parts;
}

function linkify(node: MdastNode, matchers: readonly LinkMatcher[]): void {
  if (!node.children || SKIPPED_PARENTS.has(node.type)) return;
  node.children = node.children.flatMap((child) => {
    if (child.type === "text") return splitText(child, matchers);
    linkify(child, matchers);
    return [child];
  });
}

/**
 * Remark plugin applying link rules to text. It runs after item labels have
 * become links, and never touches links, code or raw HTML.
 */
export function remarkLinkRules(matchers: readonly LinkMatcher[]) {
  return (tree: MdastNode) => {
    if (matchers.length > 0) linkify(tree, matchers);
  };
}

/** Compiled matchers for the chat markdown under this provider; empty turns rules off. */
export const LinkRuleMatchersContext = createContext<readonly LinkMatcher[]>([]);

/** Split a session reference href into the session and optional message ids. */
export function parseSessionReference(
  href: string,
): { sessionId: string; messageId: string | null } | null {
  if (!href.startsWith(SESSION_REFERENCE_HREF_PREFIX)) return null;
  const [sessionId, messageId] = href.slice(SESSION_REFERENCE_HREF_PREFIX.length).split("/");
  if (!/^[A-Za-z0-9_-]{6,64}$/.test(sessionId ?? "")) return null;
  if (messageId !== undefined && !/^[A-Za-z0-9_-]{1,128}$/.test(messageId)) return null;
  return { sessionId, messageId: messageId ?? null };
}
