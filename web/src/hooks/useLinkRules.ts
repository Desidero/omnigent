import { useQuery } from "@tanstack/react-query";
import { getLinkRules, type LinkRuleSettings } from "@/lib/linkRulesApi";

/** Shared cache key, so a saved rule reaches every open transcript. */
export const LINK_RULES_QUERY_KEY = ["preferences", "shared", "link_rules"];

/** The user's chat link rules, saved or default. */
export function useLinkRules() {
  return useQuery<LinkRuleSettings>({
    queryKey: LINK_RULES_QUERY_KEY,
    queryFn: getLinkRules,
    staleTime: 60_000,
  });
}
