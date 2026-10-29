import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { SettingsGroup } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { LINK_RULES_QUERY_KEY, useLinkRules } from "@/hooks/useLinkRules";
import {
  compileLinkRules,
  GIT_PROVIDERS,
  type GitProviderId,
  type LinkRule,
  linkRuleErrors,
  MAX_LINK_RULES,
  remarkLinkRules,
} from "@/lib/linkRules";
import { saveLinkRules } from "@/lib/linkRulesApi";
import { ApiError } from "@/lib/sessionsApi";
import { CHAT_LINK_RULES_ENTRY } from "@/pages/settings/search/catalog/general";
import { SettingsItem } from "@/pages/settings/search/SettingsItem";
import { settingsControlProps } from "@/pages/settings/search/settingsControl";
import { SettingsContent, SettingsDataRegion } from "@/pages/settings/search/settingsOwnership";

const DEFAULT_SAMPLE =
  "Fixes acme/web#12 and ABC-345 (see ENG-6). Earlier: session:0123456789abcdef. `ABC-1` in code stays text.";

const SESSION_DESCRIPTION =
  "session:<id> and session:<id>/<message id> open that session, or a message in it.";

function gitDescription(rule: LinkRule): string {
  const notation = rule.provider ? GIT_PROVIDERS[rule.provider] : null;
  const request = notation?.requestPrefix === "!" ? ", !123" : "";
  const github =
    rule.provider === "github"
      ? " The first GitHub host also links owner/repo#123 in every other session."
      : "";
  return `#123, issue #123, PR #123${request} and owner/repo#123 link in sessions whose repository is on this host.${github}`;
}

function uniqueName(rules: readonly LinkRule[], base: string): string {
  const taken = new Set(rules.map((rule) => rule.name.trim().toLowerCase()));
  let number = 1;
  while (taken.has(`${base} ${number}`.toLowerCase())) number += 1;
  return `${base} ${number}`;
}

function newUrlRule(rules: readonly LinkRule[]): LinkRule {
  return { name: uniqueName(rules, "Rule"), kind: "url", pattern: "", url: "", enabled: true };
}

function newGitRule(rules: readonly LinkRule[]): LinkRule {
  return {
    name: uniqueName(rules, "Git host"),
    kind: "git",
    provider: "gitlab",
    host: "",
    pattern: "",
    url: null,
    enabled: true,
  };
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
  // The preview has no session, so only GitHub's owner/repo#123 links there.
  const previewPlugins = useMemo(
    () => [
      remarkGfm,
      [remarkLinkRules, compileLinkRules(rules, null)] as [typeof remarkLinkRules, unknown],
    ],
    [rules],
  );

  if (!current) {
    return (
      <SettingsGroup title="Chat links" testId="settings-group-link-rules">
        <SettingsItem entry={CHAT_LINK_RULES_ENTRY}>
          <p className="text-sm text-muted-foreground">
            {query.isError ? "Chat links are unavailable." : "Loading chat links…"}
          </p>
        </SettingsItem>
      </SettingsGroup>
    );
  }

  const editable = current.supported && !saving;
  const update = (index: number, change: Partial<LinkRule>) =>
    setDraft(rules.map((rule, at) => (at === index ? { ...rule, ...change } : rule)));
  const missingSession = !rules.some((rule) => rule.kind === "session");

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
      <SettingsItem entry={CHAT_LINK_RULES_ENTRY}>
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
        <SettingsDataRegion
          entry={CHAT_LINK_RULES_ENTRY}
          region="rules"
          className="mt-2 flex flex-col"
        >
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
        </SettingsDataRegion>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            {...settingsControlProps(CHAT_LINK_RULES_ENTRY, "addRule")}
            variant="outline"
            size="sm"
            disabled={!editable || rules.length >= MAX_LINK_RULES}
            onClick={() => setDraft([...rules, newUrlRule(rules)])}
            data-testid="link-rules-add"
            componentId="settings.general.link_rules.add"
          >
            Add rule
          </Button>
          <Button
            {...settingsControlProps(CHAT_LINK_RULES_ENTRY, "addGitHost")}
            variant="outline"
            size="sm"
            disabled={!editable || rules.length >= MAX_LINK_RULES}
            onClick={() => setDraft([...rules, newGitRule(rules)])}
            data-testid="link-rules-add-git"
            componentId="settings.general.link_rules.add_git"
          >
            Add git host
          </Button>
          {missingSession && (
            <Button
              {...settingsControlProps(CHAT_LINK_RULES_ENTRY, "addSessions")}
              variant="outline"
              size="sm"
              disabled={!editable || rules.length >= MAX_LINK_RULES}
              onClick={() =>
                setDraft([
                  ...rules,
                  { name: "Sessions", kind: "session", pattern: "", url: null, enabled: true },
                ])
              }
              data-testid="link-rules-add-session"
              componentId="settings.general.link_rules.add_session"
            >
              Add session references
            </Button>
          )}
          <span className="flex-1" />
          {draft !== null && (
            <Button
              {...settingsControlProps(CHAT_LINK_RULES_ENTRY, "discard")}
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
            {...settingsControlProps(CHAT_LINK_RULES_ENTRY, "reset")}
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
            {...settingsControlProps(CHAT_LINK_RULES_ENTRY, "save")}
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
            {...settingsControlProps(CHAT_LINK_RULES_ENTRY, "preview")}
            id="link-rules-preview-input"
            className="mt-2"
            rows={2}
            value={sample}
            onChange={(event) => setSample(event.target.value)}
            data-testid="link-rules-preview-input"
          />
          <div data-testid="link-rules-preview">
            <SettingsContent
              entry={CHAT_LINK_RULES_ENTRY}
              area="preview"
              className="mt-2 rounded-md border border-border p-3 text-sm [&_code]:font-mono [&_code]:text-xs"
            >
              <ReactMarkdown
                remarkPlugins={previewPlugins}
                skipHtml
                components={LINK_PREVIEW_COMPONENTS}
              >
                {sample}
              </ReactMarkdown>
            </SettingsContent>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            The preview has no session, so only GitHub&rsquo;s owner/repo#123 links here. PR #123,
            issue #123 and !123 link in a session whose repository is on a listed git host. A bare
            #123 links only to a pull request the session links.
          </p>
        </div>
      </SettingsItem>
    </SettingsGroup>
  );
}

// The preview's element map: a rule's link opens in a new tab; a session reference, which
// only the chat can open, shows as text.
const LINK_PREVIEW_COMPONENTS: Components = {
  img: ({ alt }) => <span>{alt}</span>,
  a: ({ href, title, children }) =>
    href && /^[a-z][a-z\d+.-]*:/i.test(href) ? (
      <a
        href={href}
        title={title ?? undefined}
        rel="noreferrer"
        target="_blank"
        className="text-primary underline underline-offset-2"
      >
        {children}
      </a>
    ) : (
      <span className="underline underline-offset-2">{children}</span>
    ),
};

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
  // Every rule shows the same fields, so each is named after its own rule.
  const ruleName = rule.name.trim() || `rule ${index + 1}`;
  return (
    <section
      data-settings-region-row
      aria-label={`Chat link rule ${ruleName}`}
      className="mt-4 border-t border-border pt-4"
      data-testid={`link-rule-${index}`}
    >
      <div className="flex items-center gap-3">
        <Switch
          data-settings-row-action="use"
          checked={rule.enabled}
          disabled={disabled}
          onCheckedChange={(enabled) => onChange({ enabled })}
          aria-label="Use rule"
          data-testid={`link-rule-${index}-enabled`}
          componentId="settings.general.link_rules.enabled"
        />
        <Input
          data-settings-row-field="name"
          className="h-8 max-w-48"
          value={rule.name}
          disabled={disabled}
          onChange={(event) => onChange({ name: event.target.value })}
          aria-label={`Name of rule ${index + 1}`}
          aria-describedby={error ? errorId : undefined}
          data-testid={`link-rule-${index}-name`}
        />
        <span className="text-xs text-muted-foreground">
          {rule.kind === "url" ? "Link" : rule.kind === "git" ? "Git host" : "Built in"}
        </span>
        <span className="flex-1" />
        <Button
          data-settings-row-action="delete"
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={onDelete}
          aria-label="Delete rule"
          data-testid={`link-rule-${index}-delete`}
          componentId="settings.general.link_rules.delete"
        >
          Delete
        </Button>
      </div>
      {rule.kind === "url" ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <Input
            data-settings-row-field="pattern"
            className="h-8 font-mono"
            value={rule.pattern}
            disabled={disabled}
            placeholder="BST-{num} or /regex/"
            onChange={(event) => onChange({ pattern: event.target.value })}
            aria-label={`Pattern for ${ruleName}`}
            aria-describedby={error ? errorId : undefined}
            data-testid={`link-rule-${index}-pattern`}
          />
          <Input
            data-settings-row-field="url"
            className="h-8 font-mono"
            value={rule.url ?? ""}
            disabled={disabled}
            placeholder="https://jira.example.com/browse/BST-{num}"
            onChange={(event) => onChange({ url: event.target.value })}
            aria-label={`Link URL for ${ruleName}`}
            aria-describedby={error ? errorId : undefined}
            data-testid={`link-rule-${index}-url`}
          />
        </div>
      ) : rule.kind === "git" ? (
        <>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <select
              data-settings-row-field="provider"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={rule.provider ?? ""}
              disabled={disabled}
              onChange={(event) => onChange({ provider: event.target.value as GitProviderId })}
              aria-label={`Git provider for ${ruleName}`}
              data-testid={`link-rule-${index}-provider`}
            >
              {(Object.keys(GIT_PROVIDERS) as GitProviderId[]).map((provider) => (
                <option key={provider} value={provider}>
                  {GIT_PROVIDERS[provider].label}
                </option>
              ))}
            </select>
            <Input
              data-settings-row-field="host"
              className="h-8 font-mono"
              value={rule.host ?? ""}
              disabled={disabled}
              placeholder="gitlab.example.com"
              onChange={(event) => onChange({ host: event.target.value })}
              aria-label={`Host for ${ruleName}`}
              aria-describedby={error ? errorId : undefined}
              data-testid={`link-rule-${index}-host`}
            />
          </div>
          <p className="mt-2 text-sm text-muted-foreground">{gitDescription(rule)}</p>
        </>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">{SESSION_DESCRIPTION}</p>
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
    </section>
  );
}
