// Chat link rules: short references such as `BST-2135`, `PR #123` or
// `session:<id>` that chat messages render as links. The server validates a
// rule when it is saved (omnigent/link_rules.py); this module checks it again
// before compiling, with the same rules, because every viewer's browser runs
// the result on every message. See docs/chat-link-rules.md.
//
// `git` rules list git hosts. The session's repository picks the one that
// links bare `#123`, `issue #123`, `PR #123` and the provider's `!123`; the
// GitHub rule links `owner/repo#123` in every session.
//
// Compiled regexes avoid lookbehind and named groups, which older Safari can't
// parse: a match's leading boundary is consumed as group 1 instead.

import { createContext } from "react";

export type LinkRuleKind = "url" | "git" | "session";

/** Providers a `git` rule can name, by the git info payload's provider id. */
export type GitProviderId = "github" | "gitlab" | "azure_devops";

export interface LinkRule {
  name: string;
  kind: LinkRuleKind;
  /** `url` kind: a short form (`BST-{num}`) or a raw `/regex/`; `""` otherwise. */
  pattern: string;
  /** `url` kind: the http(s) template, e.g. `https://jira.example.com/browse/BST-{num}`. */
  url: string | null;
  enabled: boolean;
  /** `git` kind: the host's provider. */
  provider?: GitProviderId | null;
  /** `git` kind: a bare host name with an optional port, e.g. `gitlab.example.com`. */
  host?: string | null;
}

export interface GitProviderNotation {
  label: string;
  defaultHost: string;
  /** The marker before a pull request number: `#` on GitHub, `!` on GitLab and Azure DevOps. */
  requestPrefix: string;
}

/** Mirrors `GIT_PROVIDERS` in omnigent/link_rules.py. */
export const GIT_PROVIDERS: Readonly<Record<GitProviderId, GitProviderNotation>> = {
  github: { label: "GitHub", defaultHost: "github.com", requestPrefix: "#" },
  gitlab: { label: "GitLab", defaultHost: "gitlab.com", requestPrefix: "!" },
  azure_devops: { label: "Azure DevOps", defaultHost: "dev.azure.com", requestPrefix: "!" },
};

function isGitProvider(value: unknown): value is GitProviderId {
  return typeof value === "string" && Object.hasOwn(GIT_PROVIDERS, value);
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
const MAX_HOST_LENGTH = 253;
const HOST_LABEL = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
const BARE_HOST = new RegExp(`^${HOST_LABEL}(?:\\.${HOST_LABEL})*(?::([0-9]{1,5}))?$`);
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

/**
 * Check a `git` rule's host: a bare host name with an optional port, no
 * scheme, path, credentials or spaces. Hosts compare lower-cased.
 *
 * @throws LinkRuleError naming the problem.
 */
export function checkGitHost(host: string | null | undefined): void {
  if (!host) throw new LinkRuleError("host: required for a git rule, e.g. gitlab.example.com");
  const match = BARE_HOST.exec(host.toLowerCase());
  const port = match?.[1];
  if (
    host.length > MAX_HOST_LENGTH ||
    !match ||
    (port !== undefined && !(Number(port) > 0 && Number(port) < 65536))
  ) {
    throw new LinkRuleError(
      "host: a bare host name such as gitlab.example.com, with no scheme, path or credentials",
    );
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
    if (rule.kind !== "url" && rule.kind !== "git" && rule.kind !== "session") {
      return "kind: must be url, git or session";
    }
    if (rule.kind !== "url" && (rule.pattern || rule.url)) {
      return `the built-in ${rule.kind} kind takes no pattern or url`;
    }
    if (rule.kind !== "git" && (rule.provider != null || rule.host != null)) {
      return "provider and host belong to a git rule";
    }
    if (rule.kind === "url") checkUrlTemplate(rule.url ?? "", compileLinkPattern(rule.pattern));
    if (rule.kind === "git") {
      if (!isGitProvider(rule.provider)) {
        return `provider: must be ${Object.keys(GIT_PROVIDERS).join(", ")}`;
      }
      checkGitHost(rule.host);
    }
  } catch (error) {
    if (error instanceof LinkRuleError) return error.message;
    throw error;
  }
  return null;
}

/**
 * Per-rule errors for a whole list, including repeated names, two `git` rules
 * for one host and a second `session` rule; `null` where a rule is fine.
 */
export function linkRuleErrors(rules: readonly LinkRule[]): (string | null)[] {
  const names = new Set<string>();
  const hosts = new Set<string>();
  let sessions = 0;
  return rules.map((rule) => {
    const own = linkRuleError(rule);
    if (own) return own;
    const folded = rule.name.trim().toLowerCase();
    if (names.has(folded)) return `two rules are named ${rule.name.trim()}`;
    names.add(folded);
    if (rule.kind === "session" && ++sessions > 1) return "only one session rule";
    if (rule.kind === "git") {
      const host = (rule.host ?? "").toLowerCase();
      if (hosts.has(host)) return `two git rules are for ${host}`;
      hosts.add(host);
    }
    return null;
  });
}

/** The session's repository, from its git info; chat references link to it. */
export interface SessionGitRepository {
  /** The provider id the server resolved, or `null` when none claims the remote. */
  provider: string | null;
  /** Scheme and host of the repository's web pages, e.g. `https://gitlab.example.com`. */
  origin: string;
  /** The repository path, e.g. `owner/repo`, `group/sub/project` or `org/project/repo`. */
  repository: string;
  /** Pull request numbers known on `repository`; GitHub's bare `#N` links those to the PR. */
  pullNumbers: ReadonlySet<number>;
}

function hostName(host: string): string {
  return host.toLowerCase().replace(/:\d+$/, "");
}

/**
 * The `git` rule that owns a session's bare references: the rule for the
 * repository's host (a disabled one turns linking off), else the first
 * enabled rule for the provider the server resolved. Mirrors
 * `session_git_rule` in omnigent/link_rules.py.
 */
export function sessionGitRule(
  rules: readonly LinkRule[],
  provider: string | null,
  host: string | null,
): LinkRule | null {
  if (!host) return null;
  const gitRules = rules.filter((rule) => rule.kind === "git" && rule.host);
  const wanted = hostName(host);
  const listed = gitRules.find((rule) => hostName(rule.host ?? "") === wanted);
  if (listed) return listed.enabled ? listed : null;
  if (!provider) return null;
  return gitRules.find((rule) => rule.enabled && rule.provider === provider) ?? null;
}

/** The enabled GitHub rule that links `owner/repo#123` in every session. */
export function githubGitRule(rules: readonly LinkRule[]): LinkRule | null {
  return (
    rules.find((rule) => rule.kind === "git" && rule.enabled && rule.provider === "github") ?? null
  );
}

/** One compiled rule: a global regex and how to turn its match into an href. */
export interface LinkMatcher {
  name: string;
  regex: RegExp;
  href: (match: RegExpExecArray) => string | null;
}

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

// Words that say which kind a git reference is; longer phrases first so the
// alternation prefers them.
const REQUEST_WORDS = ["pull request", "merge request", "pull", "pr", "mr"];
const ISSUE_WORDS = ["work item", "issue"];

/** What a git reference says it is: `issue #1`, `PR #1` / `!1`, or a bare `#1`. */
export type GitReferenceKind = "issue" | "request" | "unspecified";

/** Where one compiled git rule links: a repository on a host, with its provider's URL shapes. */
export interface GitLinkTarget {
  provider: GitProviderId;
  origin: string;
  /** The session's repository, or `null` for GitHub's own rule outside it. */
  repository: string | null;
  pullNumbers: ReadonlySet<number>;
}

/**
 * Matches a git reference. Group 1 is the leading boundary, which also keeps
 * out paths, URLs and entities (after `/`, `.`, `:`, `#`, `!` or `&`); group 2
 * an optional kind word; group 3 another repository; group 4 the marker; group
 * 5 a number of up to seven digits that nothing word-like follows.
 */
function gitReferenceRegex(marks: "#" | "#!", qualifiedOnly: boolean): RegExp {
  const words = [...REQUEST_WORDS, ...ISSUE_WORDS].join("|");
  const repository = String.raw`([A-Za-z0-9_.-]{1,100}(?:/[A-Za-z0-9_.-]{1,100}){1,4})`;
  return new RegExp(
    String.raw`(^|[^A-Za-z0-9_/.:#!&])(?:(${words})\s+)?` +
      `${repository}${qualifiedOnly ? "" : "?"}([${marks}])` +
      String.raw`(\d{1,7})(?![A-Za-z0-9_#!/-])`,
    "gi",
  );
}

function gitReferenceKind(word: string | undefined, mark: string): GitReferenceKind {
  if (word) {
    const folded = word.toLowerCase().replace(/\s+/g, " ");
    return REQUEST_WORDS.includes(folded) ? "request" : "issue";
  }
  return mark === "!" ? "request" : "unspecified";
}

const encodePath = (path: string) => path.split("/").map(encodeURIComponent).join("/");

/**
 * The page a reference names on `target`'s provider, or null when the
 * provider has no page for it. A bare GitHub `#N` goes to the pull request when
 * the session knows one by that number, else to the issue page, which GitHub
 * redirects for pull requests.
 */
export function gitReferenceUrl(
  target: GitLinkTarget,
  reference: { kind: GitReferenceKind; number: number; repository: string | null },
): string | null {
  const repository = reference.repository ?? target.repository;
  if (repository === null) return null;
  const request = reference.kind === "request";
  const sameRepository =
    target.repository !== null && repository.toLowerCase() === target.repository.toLowerCase();
  switch (target.provider) {
    case "github": {
      if (repository.split("/").length !== 2) return null;
      const pull =
        request ||
        (reference.kind === "unspecified" &&
          sameRepository &&
          target.pullNumbers.has(reference.number));
      return safeHttpUrl(
        `${target.origin}/${encodePath(repository)}/${pull ? "pull" : "issues"}/${reference.number}`,
      );
    }
    case "gitlab":
      return safeHttpUrl(
        `${target.origin}/${encodePath(repository)}/-/${request ? "merge_requests" : "issues"}/${reference.number}`,
      );
    case "azure_devops": {
      // Azure paths are `org/project/repo`; another repository has no notation.
      if (!sameRepository) return null;
      const [organization, project, name, ...rest] = repository.split("/");
      if (!organization || !project || !name || rest.length > 0) return null;
      const base = `${target.origin}/${encodeURIComponent(organization)}/${encodeURIComponent(project)}`;
      return safeHttpUrl(
        request
          ? `${base}/_git/${encodeURIComponent(name)}/pullrequest/${reference.number}`
          : `${base}/_workitems/edit/${reference.number}`,
      );
    }
    default:
      return null;
  }
}

/**
 * Whether a qualified reference outside GitHub's own host belongs to the
 * session's provider: one with the provider's `!` marker does, and GitHub
 * paths are exactly `owner/repo`, so a longer path stays, as does one under
 * the session repository's top-level owner or group. Everything else is
 * GitHub's.
 */
function staysWithSession(reference: string, mark: string, sessionRepository: string): boolean {
  const segments = reference.split("/");
  if (mark === "!" || segments.length > 2) return true;
  return segments[0].toLowerCase() === sessionRepository.split("/")[0].toLowerCase();
}

function gitMatcher(
  name: string,
  target: GitLinkTarget,
  regex: RegExp,
  accepts: (repository: string | null, mark: string) => boolean,
): LinkMatcher {
  return {
    name,
    regex,
    href: (match) => {
      const repository = match[3] ?? null;
      if (!accepts(repository, match[4])) return null;
      return gitReferenceUrl(target, {
        kind: gitReferenceKind(match[2], match[4]),
        number: Number(match[5]),
        repository,
      });
    },
  };
}

function originHost(origin: string): string | null {
  try {
    return new URL(origin).host;
  } catch {
    return null;
  }
}

/**
 * Matchers for the `git` rules, at their rules' places in the list: the
 * session's rule links bare references and its own qualified ones, and the
 * GitHub rule links every other `owner/repo#123`.
 */
function gitMatchers(
  rules: readonly LinkRule[],
  session: SessionGitRepository | null,
): Map<LinkRule, LinkMatcher[]> {
  const byRule = new Map<LinkRule, LinkMatcher[]>();
  const add = (rule: LinkRule, matcher: LinkMatcher) =>
    byRule.set(rule, [...(byRule.get(rule) ?? []), matcher]);
  const sessionHost = session === null ? null : originHost(session.origin);
  const sessionRule =
    session === null ? null : sessionGitRule(rules, session.provider, sessionHost);
  const githubRule = githubGitRule(rules);
  const githubOrigin = githubRule ? `https://${(githubRule.host ?? "").toLowerCase()}` : null;
  const githubIsSession =
    sessionRule !== null &&
    sessionHost !== null &&
    githubRule !== null &&
    hostName(sessionHost) === hostName(githubRule.host ?? "");
  if (sessionRule !== null && session !== null && isGitProvider(sessionRule.provider)) {
    const provider = sessionRule.provider;
    const marks = GIT_PROVIDERS[provider].requestPrefix === "!" ? "#!" : "#";
    const target = {
      provider,
      origin: session.origin,
      repository: session.repository,
      pullNumbers: session.pullNumbers,
    };
    add(
      sessionRule,
      gitMatcher(
        sessionRule.name,
        target,
        gitReferenceRegex(marks, false),
        (repository, mark) =>
          repository === null ||
          githubRule === null ||
          githubIsSession ||
          staysWithSession(repository, mark, session.repository),
      ),
    );
  }
  if (githubRule !== null && githubOrigin !== null && !githubIsSession) {
    const target = {
      provider: "github" as const,
      origin: githubOrigin,
      repository: null,
      pullNumbers: new Set<number>(),
    };
    add(
      githubRule,
      gitMatcher(
        githubRule.name,
        target,
        gitReferenceRegex("#", true),
        (repository, mark) =>
          repository !== null &&
          (sessionRule === null ||
            session === null ||
            !staysWithSession(repository, mark, session.repository)),
      ),
    );
  }
  return byRule;
}

/**
 * Compile the enabled rules into matchers, skipping any that fail the checks.
 *
 * @param rules - The user's rules, in priority order.
 * @param session - The session's repository, or `null` when it has none:
 *   then only GitHub's `owner/repo#123` links, and bare `#123` stays text.
 */
export function compileLinkRules(
  rules: readonly LinkRule[],
  session: SessionGitRepository | null,
): LinkMatcher[] {
  const errors = linkRuleErrors(rules);
  const valid = rules.filter((_rule, index) => errors[index] === null);
  const git = gitMatchers(valid, session);
  const matchers: LinkMatcher[] = [];
  rules.forEach((rule, index) => {
    if (!rule.enabled || errors[index] !== null) return;
    if (rule.kind === "git") {
      matchers.push(...(git.get(rule) ?? []));
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

const matcherKeys = new WeakMap<readonly LinkMatcher[], number>();
let nextMatcherKey = 1;

/**
 * A key that changes whenever the matchers do. Streamdown's memo ignores
 * `remarkPlugins`, so a message keyed on it re-parses when its rules or
 * repository arrive after it rendered.
 */
export function linkMatchersKey(matchers: readonly LinkMatcher[]): string {
  if (matchers.length === 0) return "";
  let key = matcherKeys.get(matchers);
  if (key === undefined) {
    key = nextMatcherKey++;
    matcherKeys.set(matchers, key);
  }
  return `link-rules-${key}`;
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
