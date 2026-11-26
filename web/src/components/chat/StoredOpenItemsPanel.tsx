import { Fragment, useContext, useMemo, useState, type ReactNode } from "react";
import { ChevronRightIcon, MessageSquareDotIcon, XIcon } from "lucide-react";
import {
  FilePathAwareMessageResponse,
  ItemLabelPopover,
  itemLabelChipClass,
} from "@/components/blocks/ChatMarkdown";
import { OpenItemsFilterBar } from "@/components/chat/OpenItemsFilterBar";
import { OpenItemsPanel, useDismissedItems } from "@/components/chat/OpenItemsPanel";
import { Button } from "@/components/ui/button";
import { useCanEdit } from "@/hooks/usePermissions";
import { requestItemComment, useCanCommentOnItems } from "@/lib/itemCommentDrafts";
import { useItemCommentClosingLabels } from "@/lib/openItemAnswers";
import {
  useImportChatItems,
  useStoredOpenItems,
  useUpdateStoredOpenItems,
} from "@/hooks/useStoredOpenItems";
import {
  ItemLabelIndexContext,
  ItemLabelMessageContext,
  ItemLabelSessionContext,
} from "@/lib/itemLabels";
import { MESSAGE_QUERY_PARAM } from "@/lib/messageDeepLink";
import {
  NO_OPEN_ITEM_FILTERS,
  filterOpenItemRows,
  groupOpenItemRows,
  hasOpenItemFilters,
  openItemFacetCounts,
  useOpenItemGrouping,
  useOpenItemsView,
  writeOpenItemGrouping,
} from "@/lib/openItemFilters";
import {
  chatItemsToImport,
  chatResolution,
  countOpenRows,
  openItemRows,
  RAISED_FROM_CHAT,
  type OpenItemRow,
  type OpenItemUpdate,
  type StoredOpenItem,
} from "@/lib/openItems";
import { relativeTime } from "@/lib/relativeTime";
import { useSearchParams } from "@/lib/routing";
import { cn } from "@/lib/utils";

/** What a close from the panel records when the person gives no reason. */
export const PANEL_CLOSE_RESOLUTION = "Closed from the Open items panel";

// Below this many items the list is short enough to read without search or chips.
const FILTER_BAR_MIN_ROWS = 5;
const GROUP_HEADING_CLASS = "px-3 pt-2 pb-1 text-xs text-muted-foreground";
const TAG_CLASS =
  "shrink-0 rounded-full border border-border px-1.5 text-[10px] leading-4 text-muted-foreground";

function ago(epochSeconds: number): string {
  const age = relativeTime(epochSeconds * 1000);
  return age === "now" ? "just now" : `${age} ago`;
}

function rowName(row: OpenItemRow): string {
  const state = row.status === "open" ? "" : ` (${row.status})`;
  return `Item ${row.label}${state}${row.stored ? "" : ", chat only"}`;
}

/** Markdown of an item's detail; labels in it resolve against the message that raised it. */
function ItemMarkdown({ row, text }: { row: OpenItemRow; text: string }) {
  return (
    <ItemLabelMessageContext.Provider value={row.entry?.source.messageId ?? null}>
      <FilePathAwareMessageResponse>{text}</FilePathAwareMessageResponse>
    </ItemLabelMessageContext.Provider>
  );
}

function StoredItemFacts({ item }: { item: StoredOpenItem }) {
  return (
    <>
      {item.links.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {item.links.map((link) => (
            <li key={link.url} className="truncate">
              <a
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-link hover:underline"
              >
                {link.label ?? link.url}
              </a>
            </li>
          ))}
        </ul>
      )}
      {item.answers.length > 0 && (
        <section aria-label="Answers" className="flex flex-col gap-1">
          {item.answers.map((answer) => (
            <div key={`${answer.at}:${answer.text}`} className="border-l-2 border-border pl-2">
              <div className="text-xs text-muted-foreground">
                {`Answered · ${answer.by ?? "You"} · ${ago(answer.at)}`}
              </div>
              <p className="whitespace-pre-wrap">{answer.text}</p>
            </div>
          ))}
        </section>
      )}
      {item.status === "closed" && (
        <div className="border-l-2 border-border pl-2">
          <div className="text-xs text-muted-foreground">
            {item.closed_by === "auto"
              ? "Closed in chat"
              : `Closed by ${item.closed_by === "user" ? "a person" : "the agent"}`}
            {item.closed_at !== null && ` · ${ago(item.closed_at)}`}
          </div>
          {item.resolution && <p className="whitespace-pre-wrap">{item.resolution}</p>}
        </div>
      )}
      <div className="text-xs text-muted-foreground">
        {`Raised ${ago(item.created_at)}`}
        {item.raised_by === RAISED_FROM_CHAT
          ? " · recorded from chat"
          : item.raised_by && ` for ${item.raised_by}`}
      </div>
    </>
  );
}

/** Topic editor: a slug from the topics in use, or a new one; empty clears it. */
function TopicForm({
  item,
  topics,
  onSave,
}: {
  item: StoredOpenItem;
  topics: readonly string[];
  onSave: (topic: string) => void;
}) {
  const listId = `open-item-topics-${item.label}`;
  return (
    <form
      className="flex min-w-0 items-center gap-1"
      onSubmit={(event) => {
        event.preventDefault();
        const field = new FormData(event.currentTarget).get("topic");
        onSave(typeof field === "string" ? field.trim() : "");
      }}
    >
      <input
        name="topic"
        list={listId}
        defaultValue={item.topic ?? ""}
        placeholder="Topic"
        aria-label={`Topic of ${item.label}`}
        maxLength={48}
        className="h-7 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
      />
      <datalist id={listId}>
        {topics.map((topic) => (
          <option key={topic} value={topic} />
        ))}
      </datalist>
      <Button type="submit" size="sm" variant="ghost" className="h-7 px-2 text-xs">
        Set topic
      </Button>
    </form>
  );
}

function RowDetails({
  row,
  canEdit,
  topics,
  onUpdate,
}: {
  row: OpenItemRow;
  canEdit: boolean;
  topics: readonly string[];
  onUpdate: (update: OpenItemUpdate) => void;
}) {
  const [, setSearchParams] = useSearchParams();
  const sessionId = useContext(ItemLabelSessionContext);
  const canComment = useCanCommentOnItems(sessionId);
  const [resolution, setResolution] = useState("");
  const item = row.stored;
  const messageId = row.entry?.source.messageId;
  const closedInChat = item && row.entry?.closedInChat ? chatResolution(row) : null;
  return (
    <div className="flex flex-col gap-2 px-3 pt-1 pb-2 text-sm" data-testid="open-item-details">
      {row.detail ? (
        <ItemMarkdown row={row} text={row.detail} />
      ) : (
        <p className="text-muted-foreground">{row.title}</p>
      )}
      {item && <StoredItemFacts item={item} />}
      {closedInChat !== null && (
        <div className="flex items-center justify-between gap-2 rounded-md bg-muted px-2 py-1 text-xs">
          <span>The chat closed this item; it is still open here.</span>
          {canEdit && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              onClick={() =>
                onUpdate({
                  label: row.label,
                  status: "closed",
                  resolution: closedInChat || PANEL_CLOSE_RESOLUTION,
                })
              }
            >
              Close
            </Button>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {messageId && (
          <button
            type="button"
            className="text-xs text-link hover:underline"
            onClick={() =>
              setSearchParams((previous) => {
                const next = new URLSearchParams(previous);
                next.set(MESSAGE_QUERY_PARAM, messageId);
                return next;
              })
            }
          >
            Show in conversation
          </button>
        )}
        {canComment && sessionId !== null && (
          // Comments sent on a stored item are recorded as its answers once they post.
          <button
            type="button"
            className="text-xs text-link hover:underline"
            onClick={() => requestItemComment(sessionId, { label: row.label, title: row.title })}
          >
            Comment
          </button>
        )}
        {canComment && sessionId !== null && item && item.status !== "closed" && (
          // Closes the item with the comment once the message posts.
          <button
            type="button"
            className="text-xs text-link hover:underline"
            onClick={() =>
              requestItemComment(sessionId, { label: row.label, title: row.title, closes: true })
            }
          >
            Comment and close
          </button>
        )}
        {item && canEdit && item.status !== "closed" && (
          <form
            className="flex min-w-0 flex-1 items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              onUpdate({
                label: row.label,
                status: "closed",
                resolution: resolution.trim() || PANEL_CLOSE_RESOLUTION,
              });
            }}
          >
            <input
              value={resolution}
              onChange={(event) => setResolution(event.target.value)}
              placeholder="How it ended (optional)"
              aria-label={`Resolution for ${row.label}`}
              maxLength={2000}
              className="h-7 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
            />
            <Button type="submit" size="sm" variant="outline" className="h-7 px-2 text-xs">
              Close
            </Button>
          </form>
        )}
        {item && canEdit && item.status === "closed" && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 px-2 text-xs"
            onClick={() => onUpdate({ label: row.label, status: "open" })}
          >
            Reopen
          </Button>
        )}
      </div>
      {item && canEdit && (
        <TopicForm
          item={item}
          topics={topics}
          onSave={(topic) => {
            if (topic !== (item.topic ?? "")) onUpdate({ label: row.label, topic });
          }}
        />
      )}
    </div>
  );
}

function ItemRowView({
  row,
  expanded,
  closing = false,
  onToggle,
  action,
  children,
}: {
  row: OpenItemRow;
  expanded: boolean;
  /** A comment draft closes the item when it is sent. */
  closing?: boolean;
  onToggle: () => void;
  action?: ReactNode;
  children?: ReactNode;
}) {
  const closed = row.status === "closed";
  const chip = (
    <span className={cn(itemLabelChipClass(closed, row.recent), "shrink-0")}>{row.label}</span>
  );
  return (
    <li data-testid="open-item-row" data-label={row.label} className="min-w-0">
      <div className="flex min-w-0 items-center">
        {/* The chip previews the item where the chat raised it, as chips in messages do. */}
        {row.entry?.source.messageId ? (
          <ItemLabelPopover item={row.entry}>
            <button
              type="button"
              aria-label={`Preview ${row.label} in the conversation`}
              className="ml-3 shrink-0"
            >
              {chip}
            </button>
          </ItemLabelPopover>
        ) : (
          <span className="ml-3">{chip}</span>
        )}
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={rowName(row)}
          className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left text-ui hover:bg-muted"
          onClick={onToggle}
        >
          <span className={cn("truncate", closed && "text-muted-foreground line-through")}>
            {row.title || row.label}
          </span>
          {row.status === "answered" && <span className={TAG_CLASS}>answered</span>}
          {closing && row.status !== "closed" && (
            <span className={cn(TAG_CLASS, "border-success/40 text-success")}>
              closes when sent
            </span>
          )}
          {row.entry?.closedInChat && row.status !== "closed" && (
            <span className={TAG_CLASS}>closed in chat</span>
          )}
          {!row.stored && <span className={TAG_CLASS}>chat only</span>}
          {row.topic && <span className={cn(TAG_CLASS, "ml-auto")}>{row.topic}</span>}
        </button>
        {action}
      </div>
      {expanded && children}
    </li>
  );
}

function QuickAction({
  label,
  title,
  onClick,
  children,
}: {
  label: string;
  title?: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title}
      className="mr-2 shrink-0 rounded p-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/** A group's heading, e.g. "Closed (4)": shows or folds the rows under it. */
function GroupHeading({
  title,
  count,
  folded,
  onToggle,
}: {
  title: string;
  count: number;
  folded: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        aria-expanded={!folded}
        className={cn(GROUP_HEADING_CLASS, "flex w-full items-center gap-1 hover:text-foreground")}
        onClick={onToggle}
      >
        <ChevronRightIcon
          className={cn("size-3 transition-transform", !folded && "rotate-90")}
          aria-hidden="true"
        />
        {`${title} (${count})`}
      </button>
    </li>
  );
}

/**
 * The Open items section on a server that stores them: stored items, and
 * labels only the chat has, marked "chat only", grouped by status, topic or
 * kind, with search and filter chips once the list is long. People with edit
 * access close, reopen and retopic stored items here; chat-only items are
 * dismissed as before.
 */
export function StoredOpenItemsPanel({
  stored,
  sessionId,
}: {
  stored: readonly StoredOpenItem[];
  sessionId: string | null;
}) {
  const index = useContext(ItemLabelIndexContext);
  const { dismissed, dismiss, restore } = useDismissedItems(sessionId);
  const canEdit = useCanEdit(sessionId ?? "");
  const closingLabels = useItemCommentClosingLabels(sessionId);
  const update = useUpdateStoredOpenItems(sessionId);
  const importItems = useImportChatItems(sessionId);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [view, setView] = useOpenItemsView(sessionId);
  const grouping = useOpenItemGrouping();
  const rows = useMemo(() => openItemRows(index, stored, dismissed), [index, stored, dismissed]);
  const topics = useMemo(
    () => [...new Set(stored.flatMap((item) => (item.topic ? [item.topic] : [])))].sort(),
    [stored],
  );
  const imports = useMemo(
    () => (canEdit ? chatItemsToImport(index, stored, dismissed) : []),
    [canEdit, index, stored, dismissed],
  );
  if (rows.length === 0) return null;

  const change = (patch: OpenItemUpdate) => update.mutate([patch]);
  const renderRow = (row: OpenItemRow) => {
    let action: ReactNode = null;
    if (row.stored && canEdit && row.status !== "closed") {
      action = (
        <QuickAction
          label={`Close item ${row.label}`}
          title="Close"
          onClick={() =>
            change({ label: row.label, status: "closed", resolution: PANEL_CLOSE_RESOLUTION })
          }
        >
          <XIcon className="size-3" aria-hidden="true" />
        </QuickAction>
      );
    } else if (!row.stored && row.dismissed) {
      action = (
        <QuickAction label={`Restore item ${row.label}`} onClick={() => restore(row.label)}>
          Restore
        </QuickAction>
      );
    } else if (!row.stored && row.status === "open") {
      action = (
        <QuickAction
          label={`Dismiss item ${row.label}`}
          title="Dismiss from open items"
          onClick={() => dismiss(row.label)}
        >
          <XIcon className="size-3" aria-hidden="true" />
        </QuickAction>
      );
    }
    return (
      <ItemRowView
        key={row.label}
        row={row}
        expanded={expanded === row.label}
        closing={closingLabels.has(row.label)}
        onToggle={() => setExpanded((open) => (open === row.label ? null : row.label))}
        action={action}
      >
        <RowDetails row={row} canEdit={canEdit} topics={topics} onUpdate={change} />
      </ItemRowView>
    );
  };

  const listed = rows.filter((row) => !row.dismissed);
  const filters = view.filters;
  const groups = groupOpenItemRows(filterOpenItemRows(listed, filters), grouping);
  const dismissedRows = filterOpenItemRows(
    rows.filter((row) => row.dismissed),
    filters,
  );
  if (dismissedRows.length > 0) {
    groups.push({
      key: "dismissed",
      title: "Dismissed",
      rows: dismissedRows,
      foldedByDefault: true,
    });
  }
  // A search shows every match; with a chip selected, the closed group opens too.
  const searching = filters.query.trim() !== "";
  const filtered = hasOpenItemFilters(filters);
  const isFolded = (group: (typeof groups)[number]) =>
    !searching && view.toggledGroups.includes(group.key) !== (group.foldedByDefault && !filtered);
  const toggleGroup = (key: string) =>
    setView((current) => ({
      ...current,
      toggledGroups: current.toggledGroups.includes(key)
        ? current.toggledGroups.filter((other) => other !== key)
        : [...current.toggledGroups, key],
    }));
  const setFilters = (next: typeof filters) =>
    setView((current) => ({ ...current, filters: next }));
  return (
    <section data-testid="open-items" aria-label="Open items">
      <div className="flex items-center gap-2 px-3 py-2 text-ui font-medium">
        <MessageSquareDotIcon className="size-4 shrink-0 text-muted-foreground" />
        <span>Open items</span>
        <span className="opacity-70">({countOpenRows(rows)})</span>
        {imports.length > 0 && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="ml-auto h-6 px-2 text-xs font-normal"
            title="Store the chat's own labels with the session's items"
            disabled={importItems.isPending}
            onClick={() => importItems.mutate(imports)}
          >
            {importItems.isPending ? "Importing…" : `Import ${imports.length} from chat`}
          </Button>
        )}
      </div>
      {(rows.length >= FILTER_BAR_MIN_ROWS || hasOpenItemFilters(filters)) && (
        <OpenItemsFilterBar
          filters={filters}
          counts={openItemFacetCounts(listed, filters)}
          grouping={grouping}
          onFiltersChange={setFilters}
          onGroupingChange={writeOpenItemGrouping}
        />
      )}
      <ul className="max-h-[min(24rem,50vh)] overflow-y-auto border-t border-border py-1">
        {groups.length === 0 && (
          <li className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
            No items match.
            <button
              type="button"
              className="text-link hover:underline"
              onClick={() => setFilters(NO_OPEN_ITEM_FILTERS)}
            >
              Clear filters
            </button>
          </li>
        )}
        {groups.map((group) => {
          const folded = isFolded(group);
          return (
            <Fragment key={group.key}>
              <GroupHeading
                title={group.title}
                count={group.rows.length}
                folded={folded}
                onToggle={() => toggleGroup(group.key)}
              />
              {!folded && group.rows.map(renderRow)}
            </Fragment>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * The header panel's Open items section: read from the store where the
 * server keeps open items, otherwise the chat's own tracker, unchanged.
 */
export function SessionOpenItemsSection() {
  const sessionId = useContext(ItemLabelSessionContext);
  const stored = useStoredOpenItems(sessionId);
  if (!stored) return <OpenItemsPanel layout="section" />;
  return <StoredOpenItemsPanel stored={stored} sessionId={sessionId} />;
}
