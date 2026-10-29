import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { FilePathAwareMessageResponse } from "@/components/blocks/ChatMarkdown";
import { SettingsGroup } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { LINK_RULES_QUERY_KEY, useLinkRules } from "@/hooks/useLinkRules";
import {
  compileLinkRules,
  type LinkRule,
  type LinkRuleKind,
  LinkRuleMatchersContext,
  linkRuleErrors,
  MAX_LINK_RULES,
} from "@/lib/linkRules";
import { saveLinkRules } from "@/lib/linkRulesApi";
import { ApiError } from "@/lib/sessionsApi";

const DEFAULT_SAMPLE =
  "Fixes #12 and ABC-345 (see ENG-6). Earlier: session:0123456789abcdef. `ABC-1` in code stays text.";

const BUILTIN_DESCRIPTIONS: Record<Exclude<LinkRuleKind, "url">, string> = {
  github:
    "#123 and owner/repo#123 link to issues and pull requests on the session's repository host.",
  session: "session:<id> and session:<id>/<message id> open that session, or a message in it.",
};

function newUrlRule(rules: readonly LinkRule[]): LinkRule {
  const taken = new Set(rules.map((rule) => rule.name.trim().toLowerCase()));
  let number = 1;
  while (taken.has(`rule ${number}`)) number += 1;
  return { name: `Rule ${number}`, kind: "url", pattern: "", url: "", enabled: true };
}

/** The user's chat link rules: list, edit, preview and save them. */
export function LinkRulesSettingsGroup() {
  const queryClient = useQueryClient();
  const query = useLinkRules();
  const current = query.data;
  // Unsaved edits; null while the list shows what is saved.
  const [draft, setDraft] = useState<LinkRule[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [sample, setSample] = useState(DEFAULT_SAMPLE);
  const rules = useMemo(() => draft ?? current?.rules ?? [], [draft, current]);
  const errors = useMemo(() => linkRuleErrors(rules), [rules]);
  // The preview has no session, so GitHub references stay text there.
  const matchers = useMemo(() => compileLinkRules(rules, null), [rules]);

  if (!current) {
    return (
      <SettingsGroup title="Chat links" testId="settings-group-link-rules">
        <p className="text-sm text-muted-foreground">
          {query.isError ? "Chat links are unavailable." : "Loading chat links…"}
        </p>
      </SettingsGroup>
    );
  }

  const editable = current.supported && !saving;
  const update = (index: number, change: Partial<LinkRule>) =>
    setDraft(rules.map((rule, at) => (at === index ? { ...rule, ...change } : rule)));
  const missingBuiltins = (["github", "session"] as const).filter(
    (kind) => !rules.some((rule) => rule.kind === kind),
  );

  const save = async (next: LinkRule[] | null) => {
    setSaving(true);
    setMessage(null);
    try {
      const saved = await saveLinkRules(next, current.version);
      queryClient.setQueryData(LINK_RULES_QUERY_KEY, saved);
      setDraft(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setMessage("Your rules changed on another device. Review them and save again.");
        void queryClient.invalidateQueries({ queryKey: LINK_RULES_QUERY_KEY });
      } else {
        setMessage(error instanceof ApiError ? error.message : "Couldn't save your chat links.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsGroup title="Chat links" testId="settings-group-link-rules">
      <p className="text-sm text-muted-foreground">
        Turn short references in chat messages into links. A pattern is a short form such as{" "}
        <code>BST-{"{num}"}</code> (also <code>{"{key}"}</code> and <code>{"{id}"}</code>) or a{" "}
        <code>/regex/</code>; the URL fills in the same placeholders.
      </p>
      {!current.supported && (
        <p className="mt-2 text-sm text-muted-foreground" role="note">
          These are the defaults. Saving rules needs shared preferences enabled on the server.
        </p>
      )}
      <div className="mt-2 flex flex-col">
        {rules.map((rule, index) => (
          <LinkRuleRow
            // Rules have no stable id; the position is the identity while editing.
            // oxlint-disable-next-line react/no-array-index-key
            key={index}
            index={index}
            rule={rule}
            error={errors[index]}
            disabled={!editable}
            onChange={(change) => update(index, change)}
            onDelete={() => setDraft(rules.filter((_rule, at) => at !== index))}
          />
        ))}
        {rules.length === 0 && (
          <p className="mt-4 text-sm text-muted-foreground">
            No rules: messages show no extra links.
          </p>
        )}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!editable || rules.length >= MAX_LINK_RULES}
          onClick={() => setDraft([...rules, newUrlRule(rules)])}
          data-testid="link-rules-add"
          componentId="settings.general.link_rules.add"
        >
          Add rule
        </Button>
        {missingBuiltins.map((kind) => (
          <Button
            key={kind}
            variant="outline"
            size="sm"
            disabled={!editable || rules.length >= MAX_LINK_RULES}
            onClick={() =>
              setDraft([
                ...rules,
                {
                  name: kind === "github" ? "GitHub" : "Sessions",
                  kind,
                  pattern: "",
                  url: null,
                  enabled: true,
                },
              ])
            }
            data-testid={`link-rules-add-${kind}`}
            componentId={`settings.general.link_rules.add_${kind}`}
          >
            {kind === "github" ? "Add GitHub references" : "Add session references"}
          </Button>
        ))}
        <span className="flex-1" />
        {draft !== null && (
          <Button
            variant="ghost"
            size="sm"
            disabled={saving}
            onClick={() => {
              setDraft(null);
              setMessage(null);
            }}
            data-testid="link-rules-discard"
            componentId="settings.general.link_rules.discard"
          >
            Discard
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={!editable || (!current.saved && draft === null)}
          onClick={() => void save(null)}
          data-testid="link-rules-reset"
          componentId="settings.general.link_rules.reset"
        >
          Reset to defaults
        </Button>
        <Button
          size="sm"
          disabled={!editable || draft === null || errors.some((error) => error !== null)}
          onClick={() => void save(rules)}
          data-testid="link-rules-save"
          componentId="settings.general.link_rules.save"
        >
          Save
        </Button>
      </div>
      {message && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {message}
        </p>
      )}
      <div className="mt-4 border-t border-border pt-4">
        <label className="text-sm font-medium" htmlFor="link-rules-preview-input">
          Preview
        </label>
        <Textarea
          id="link-rules-preview-input"
          className="mt-2"
          rows={2}
          value={sample}
          onChange={(event) => setSample(event.target.value)}
          data-testid="link-rules-preview-input"
        />
        <div
          className="mt-2 rounded-md border border-border p-3 text-sm"
          data-testid="link-rules-preview"
        >
          <LinkRuleMatchersContext.Provider value={matchers}>
            <FilePathAwareMessageResponse>{sample}</FilePathAwareMessageResponse>
          </LinkRuleMatchersContext.Provider>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          GitHub references link only in a session whose repository is on GitHub.
        </p>
      </div>
    </SettingsGroup>
  );
}

function LinkRuleRow({
  index,
  rule,
  error,
  disabled,
  onChange,
  onDelete,
}: {
  index: number;
  rule: LinkRule;
  error: string | null;
  disabled: boolean;
  onChange: (change: Partial<LinkRule>) => void;
  onDelete: () => void;
}) {
  const errorId = `link-rule-${index}-error`;
  return (
    <div className="mt-4 border-t border-border pt-4" data-testid={`link-rule-${index}`}>
      <div className="flex items-center gap-3">
        <Switch
          checked={rule.enabled}
          disabled={disabled}
          onCheckedChange={(enabled) => onChange({ enabled })}
          aria-label={`Use ${rule.name || "this rule"}`}
          data-testid={`link-rule-${index}-enabled`}
          componentId="settings.general.link_rules.enabled"
        />
        <Input
          className="h-8 max-w-48"
          value={rule.name}
          disabled={disabled}
          onChange={(event) => onChange({ name: event.target.value })}
          aria-label="Rule name"
          aria-describedby={error ? errorId : undefined}
          data-testid={`link-rule-${index}-name`}
        />
        <span className="text-xs text-muted-foreground">
          {rule.kind === "url" ? "Link" : "Built in"}
        </span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={onDelete}
          aria-label={`Delete ${rule.name || "this rule"}`}
          data-testid={`link-rule-${index}-delete`}
          componentId="settings.general.link_rules.delete"
        >
          Delete
        </Button>
      </div>
      {rule.kind === "url" ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <Input
            className="h-8 font-mono"
            value={rule.pattern}
            disabled={disabled}
            placeholder="BST-{num} or /regex/"
            onChange={(event) => onChange({ pattern: event.target.value })}
            aria-label="Pattern"
            aria-describedby={error ? errorId : undefined}
            data-testid={`link-rule-${index}-pattern`}
          />
          <Input
            className="h-8 font-mono"
            value={rule.url ?? ""}
            disabled={disabled}
            placeholder="https://jira.example.com/browse/BST-{num}"
            onChange={(event) => onChange({ url: event.target.value })}
            aria-label="Link URL"
            aria-describedby={error ? errorId : undefined}
            data-testid={`link-rule-${index}-url`}
          />
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">{BUILTIN_DESCRIPTIONS[rule.kind]}</p>
      )}
      {error && (
        <p
          id={errorId}
          className="mt-1 text-sm text-destructive"
          data-testid={`link-rule-${index}-error`}
        >
          {error}
        </p>
      )}
    </div>
  );
}
