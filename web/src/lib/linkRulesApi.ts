// The user's chat link rules (`/v1/link-rules`), stored by the server as the
// `link_rules` shared preference. See docs/chat-link-rules.md.

import { authenticatedFetch } from "./identity";
import type { LinkRule } from "./linkRules";
import { apiErrorFromResponse } from "./sessionsApi";

/** The rules in effect for the caller. */
export interface LinkRuleSettings {
  /** False when the server can't save rules (no shared preferences, or too old). */
  supported: boolean;
  /** False while the defaults apply. */
  saved: boolean;
  /** Sent back as `expected_version`; `0` when nothing is saved. */
  version: number;
  rules: LinkRule[];
  defaults: LinkRule[];
}

/** What a server without the route offers: nothing to save and no rules. */
export const UNSUPPORTED_LINK_RULES: LinkRuleSettings = {
  supported: false,
  saved: false,
  version: 0,
  rules: [],
  defaults: [],
};

function normalizeRule(rule: LinkRule): LinkRule {
  return { ...rule, pattern: rule.pattern ?? "", url: rule.url ?? null };
}

function normalize(settings: LinkRuleSettings): LinkRuleSettings {
  return {
    ...settings,
    rules: settings.rules.map(normalizeRule),
    defaults: settings.defaults.map(normalizeRule),
  };
}

/** Read the caller's link rules: the saved list, or the defaults. */
export async function getLinkRules(): Promise<LinkRuleSettings> {
  const res = await authenticatedFetch("/v1/link-rules");
  if (res.status === 404) return UNSUPPORTED_LINK_RULES;
  if (!res.ok) throw await apiErrorFromResponse(res);
  return normalize((await res.json()) as LinkRuleSettings);
}

/**
 * Replace the caller's link rules.
 *
 * @param rules - The whole list, or `null` to restore the defaults.
 * @param expectedVersion - The version the edit replaces; a stale one is
 *   refused with a 409 `ApiError`.
 * @returns The rules as stored afterwards.
 */
export async function saveLinkRules(
  rules: LinkRule[] | null,
  expectedVersion: number,
): Promise<LinkRuleSettings> {
  const res = await authenticatedFetch("/v1/link-rules", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rules:
        rules === null
          ? null
          : rules.map(({ name, kind, pattern, url, enabled }) => ({
              name,
              kind,
              enabled,
              ...(kind === "url" ? { pattern, url } : {}),
            })),
      expected_version: expectedVersion,
    }),
  });
  if (!res.ok) throw await apiErrorFromResponse(res);
  return normalize((await res.json()) as LinkRuleSettings);
}
