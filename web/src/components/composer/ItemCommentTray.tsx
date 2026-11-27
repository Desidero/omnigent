import { useId, useState } from "react";
import {
  ArrowUpIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CircleCheckIcon,
  EllipsisIcon,
  MessageSquareTextIcon,
  PaperclipIcon,
  PencilIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";

import { ItemLabelDefinition, itemLabelChipClass } from "@/components/blocks/ChatMarkdown";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ITEM_COMMENT_TRAY_ID,
  useItemCommentTrayExpanded,
  type ItemCommentDraft,
} from "@/lib/itemCommentDrafts";
import type { ItemLabelEntry } from "@/lib/itemLabels";
import { cn } from "@/lib/utils";

/** Matches the queued-messages strip, so both trays read as one stack. */
const ACTION_BUTTON_CLASS =
  "shrink-0 text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground max-md:size-11";
const ACTION_ICON_CLASS = "size-3.5 max-md:size-4";
const LABEL_BADGE_CLASS = cn(itemLabelChipClass(false), "pointer-events-none shrink-0");
const NOTHING_SENDING_ELSEWHERE: { submissionId: string; commentCount: number }[] = [];
const NO_LABELS: ReadonlySet<string> = new Set();
/** Marks an item that sending closes ("Comment and close"). */
const CLOSES_TAG_CLASS = "shrink-0 rounded bg-success/15 px-1 text-xs font-medium text-success";

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/**
 * "3 comments · Q2 ×2 · R1 · closes Q2"; `composingLabel` counts a comment
 * still being written, and `composingCloses` whether it closes its item.
 */
export function summarizeItemCommentDrafts(
  drafts: readonly ItemCommentDraft[],
  composingLabel: string | null = null,
  composingCloses = false,
): string {
  const labels = drafts.map((draft) => draft.label);
  if (composingLabel !== null) labels.push(composingLabel);
  const counts = new Map<string, number>();
  for (const label of labels) counts.set(label, (counts.get(label) ?? 0) + 1);
  const parts = [...counts].map(([label, count]) => (count > 1 ? `${label} ×${count}` : label));
  const closing = new Set(drafts.filter((draft) => draft.closes).map((draft) => draft.label));
  if (composingLabel !== null && composingCloses) closing.add(composingLabel);
  if (closing.size > 0) parts.push(`closes ${[...closing].join(", ")}`);
  return [plural(labels.length, "comment"), ...parts].join(" · ");
}

/** The tray's send button text, e.g. "Send 3 comments + message". */
export function itemCommentSendLabel(commentCount: number, withMessage: boolean): string {
  return `Send ${plural(commentCount, "comment")}${withMessage ? " + message" : ""}`;
}

/** The phone-width send button text, e.g. "Send 3 + message". */
export function itemCommentSendShortLabel(commentCount: number, withMessage: boolean): string {
  return `Send ${commentCount}${withMessage ? " + message" : ""}`;
}

function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim() !== "") ?? "";
}

/** Switches "Comment and close" for one item's comments. */
function CloseToggle({
  label,
  closes,
  onToggle,
}: {
  label: string;
  closes: boolean;
  onToggle: (label: string) => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      aria-pressed={closes}
      aria-label={`Close ${label} when sent`}
      title={closes ? `Sending closes ${label}; tap to only comment` : `Comment and close ${label}`}
      className={cn(ACTION_BUTTON_CLASS, closes && "text-success hover:text-success")}
      onClick={() => onToggle(label)}
    >
      <CircleCheckIcon className={ACTION_ICON_CLASS} aria-hidden="true" />
    </Button>
  );
}

function DraftRow({
  draft,
  editing,
  closable,
  onEdit,
  onDelete,
  onToggleClose,
}: {
  draft: ItemCommentDraft;
  editing: boolean;
  /** Whether "Comment and close" is offered on the draft's item. */
  closable: boolean;
  onEdit: (draftId: string) => void;
  onDelete: (draftId: string) => void;
  onToggleClose?: (label: string) => void;
}) {
  const closes = closable && draft.closes === true;
  const preview = firstLine(draft.text);
  return (
    <div
      role="listitem"
      data-testid="item-comment-draft-row"
      className="flex min-w-0 items-center gap-1.5 py-0.5 text-sm text-foreground"
    >
      <span className={LABEL_BADGE_CLASS}>{draft.label}</span>
      {closes && <span className={CLOSES_TAG_CLASS}>closes</span>}
      <span
        className={cn("min-w-0 flex-1 truncate", !preview && "text-muted-foreground")}
        title={draft.text}
      >
        {editing ? "Editing…" : preview || "Attachment only"}
      </span>
      {draft.files.length > 0 && (
        <span
          className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground tabular-nums"
          title={draft.files.map((file) => file.name).join("\n")}
        >
          <PaperclipIcon className="size-3" aria-hidden="true" />
          {draft.files.length}
          <span className="sr-only"> attachments</span>
        </span>
      )}
      <span className="flex shrink-0 items-center">
        {closable && onToggleClose && (
          <CloseToggle label={draft.label} closes={closes} onToggle={onToggleClose} />
        )}
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label={`Edit draft on ${draft.label}`}
          className={ACTION_BUTTON_CLASS}
          disabled={editing}
          onClick={() => onEdit(draft.id)}
        >
          <PencilIcon className={ACTION_ICON_CLASS} aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label={`Delete draft on ${draft.label}`}
          className={ACTION_BUTTON_CLASS}
          onClick={() => onDelete(draft.id)}
        >
          <Trash2Icon className={ACTION_ICON_CLASS} aria-hidden="true" />
        </Button>
      </span>
    </div>
  );
}

interface ItemCommentTrayProps {
  /** Unsent drafts, in the order the items were defined. */
  drafts: readonly ItemCommentDraft[];
  /** The draft loaded into the composer, if one is being edited. */
  editingDraftId: string | null;
  /** The item of a new comment being written, which sending includes. */
  composingLabel?: string | null;
  /** Whether the comment being written closes its item. */
  composingCloses?: boolean;
  /** Items "Comment and close" is offered on: stored items that are not closed. */
  closableLabels?: ReadonlySet<string>;
  /** Switches whether an item's comments close it. */
  onToggleClose?: (label: string) => void;
  /** Whether a typed message goes along as the General section. */
  withMessage?: boolean;
  /** Why sending is unavailable right now; null when it can send. */
  sendDisabledReason?: string | null;
  onSend: () => void;
  /** Sends the drafts and leaves the typed message; offered with `onSendMessageOnly`. */
  onSendCommentsOnly?: () => void;
  /** Sends the typed message and leaves the drafts. */
  onSendMessageOnly?: () => void;
  onEdit: (draftId: string) => void;
  onDelete: (draftId: string) => void;
  onDiscardAll: () => void;
  /** Comments another tab submitted and hasn't posted yet, which it can give back. */
  sendingElsewhere?: { submissionId: string; commentCount: number }[];
  onRestoreSubmission?: (submissionId: string) => void;
  /** Width class matching the surface the tray docks onto. */
  widthClassName?: string;
}

/**
 * Comment drafts, docked above the composer like the queued-messages strip.
 * Starts collapsed to one line; its send button, which sends every comment as
 * one message, shows either way. Renders nothing without drafts.
 */
export function ItemCommentTray({
  drafts,
  editingDraftId,
  composingLabel = null,
  composingCloses = false,
  closableLabels = NO_LABELS,
  onToggleClose,
  withMessage = false,
  sendDisabledReason = null,
  onSend,
  onSendCommentsOnly,
  onSendMessageOnly,
  onEdit,
  onDelete,
  onDiscardAll,
  sendingElsewhere = NOTHING_SENDING_ELSEWHERE,
  onRestoreSubmission,
  widthClassName,
}: ItemCommentTrayProps) {
  const [expanded, setExpanded] = useItemCommentTrayExpanded();
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const messageNoteId = useId();
  if (drafts.length === 0 && sendingElsewhere.length === 0) return null;
  const commentCount = drafts.length + (composingLabel !== null ? 1 : 0);
  const showDiscard = expanded && drafts.length > 0;

  return (
    <section
      id={ITEM_COMMENT_TRAY_ID}
      tabIndex={-1}
      aria-label="Comment drafts"
      data-testid="item-comment-tray"
      className={cn(
        "composer-queued-surface mx-auto -mb-4 flex w-full flex-col rounded-t-2xl px-2 pt-1.5 pb-5.5 outline-none md:px-3",
        widthClassName,
      )}
    >
      <div className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse comment drafts" : "Show comment drafts"}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded py-1 text-left hover:text-foreground max-md:min-h-11"
          onClick={() => setExpanded(!expanded)}
        >
          <MessageSquareTextIcon className="size-3.5 shrink-0" aria-hidden="true" />
          {expanded ? (
            <span className="truncate">
              <span className="font-medium text-foreground">Comment drafts</span>
              {" · only on this browser"}
            </span>
          ) : (
            <span className="truncate text-foreground">
              {summarizeItemCommentDrafts(
                drafts.map((draft) =>
                  draft.closes && !closableLabels.has(draft.label)
                    ? { ...draft, closes: false }
                    : draft,
                ),
                composingLabel,
                composingCloses,
              )}
            </span>
          )}
          {expanded ? (
            <ChevronDownIcon className="size-3.5 shrink-0" aria-hidden="true" />
          ) : (
            <ChevronUpIcon className="size-3.5 shrink-0" aria-hidden="true" />
          )}
        </button>
        {showDiscard && (
          <span className="flex shrink-0 items-center gap-1">
            {confirmingDiscard ? (
              <>
                <span className="text-foreground">Discard {drafts.length}?</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Confirm discard all drafts"
                  className={ACTION_BUTTON_CLASS}
                  onClick={() => {
                    setConfirmingDiscard(false);
                    onDiscardAll();
                  }}
                >
                  <CheckIcon className={ACTION_ICON_CLASS} aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Keep drafts"
                  className={ACTION_BUTTON_CLASS}
                  onClick={() => setConfirmingDiscard(false)}
                >
                  <XIcon className={ACTION_ICON_CLASS} aria-hidden="true" />
                </Button>
              </>
            ) : (
              <button
                type="button"
                className="rounded px-1 py-1 hover:text-foreground max-md:min-h-11"
                onClick={() => setConfirmingDiscard(true)}
              >
                Discard all
              </button>
            )}
          </span>
        )}
        {commentCount > 0 && !(showDiscard && confirmingDiscard) && (
          <>
            {/* Phones get the short label; either may truncate rather than overflow. */}
            <Button
              type="button"
              size="sm"
              data-testid="submit-item-comments"
              className="ml-1 h-7 min-w-0 shrink gap-1 px-2 max-md:h-9"
              disabled={sendDisabledReason !== null}
              title={sendDisabledReason ?? undefined}
              aria-label={itemCommentSendLabel(commentCount, withMessage)}
              aria-describedby={withMessage ? messageNoteId : undefined}
              onClick={onSend}
            >
              <ArrowUpIcon className="size-3.5" viewBox="4 4 16 16" aria-hidden="true" />
              <span className="truncate max-sm:hidden">
                {itemCommentSendLabel(commentCount, withMessage)}
              </span>
              <span className="truncate sm:hidden">
                {itemCommentSendShortLabel(commentCount, withMessage)}
              </span>
            </Button>
            {withMessage && (
              <span id={messageNoteId} className="sr-only">
                The message you typed goes along as a General note.
              </span>
            )}
            {onSendCommentsOnly && onSendMessageOnly && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="More send options"
                    title="More send options"
                    className={ACTION_BUTTON_CLASS}
                    disabled={sendDisabledReason !== null}
                  >
                    <EllipsisIcon className={ACTION_ICON_CLASS} aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="top" align="end">
                  <DropdownMenuItem onSelect={onSendCommentsOnly}>
                    <MessageSquareTextIcon aria-hidden="true" />
                    Send comments only
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onSendMessageOnly}>
                    <ArrowUpIcon viewBox="4 4 16 16" aria-hidden="true" />
                    Send message only
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </>
        )}
      </div>
      {expanded && (
        <div
          role="list"
          aria-label="Comment drafts"
          className="flex max-h-32 flex-col gap-0.5 overflow-y-auto overscroll-contain"
        >
          {drafts.map((draft) => (
            <DraftRow
              key={draft.id}
              draft={draft}
              editing={draft.id === editingDraftId}
              closable={closableLabels.has(draft.label)}
              onEdit={onEdit}
              onDelete={onDelete}
              {...(onToggleClose ? { onToggleClose } : {})}
            />
          ))}
          {composingLabel !== null && (
            <div
              role="listitem"
              className="flex min-w-0 items-center gap-1.5 py-0.5 text-sm text-muted-foreground"
            >
              <span className={LABEL_BADGE_CLASS}>{composingLabel}</span>
              {composingCloses && <span className={CLOSES_TAG_CLASS}>closes</span>}
              <span className="min-w-0 flex-1 truncate">Writing…</span>
            </div>
          )}
          {sendingElsewhere.map(({ submissionId, commentCount: sendingCount }) => (
            <div
              key={submissionId}
              role="listitem"
              className="flex min-w-0 items-center gap-2 py-0.5 text-sm text-muted-foreground"
            >
              <span className="min-w-0 flex-1 truncate">
                {plural(sendingCount, "comment")} sending from another tab
              </span>
              {onRestoreSubmission && (
                <button
                  type="button"
                  className="shrink-0 text-xs text-link hover:underline max-md:min-h-11"
                  onClick={() => onRestoreSubmission(submissionId)}
                >
                  Back to drafts
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** Caps the expanded definition at a third of the visible viewport, keyboard included. */
const DEFINITION_MAX_HEIGHT_CLASS = "max-h-[calc(var(--omnigent-viewport-height,100dvh)/3)]";

/**
 * Comment mode's header card at the top of the composer: names the item the
 * comment is for and shows its definition, expanded until collapsed to one
 * line. × leaves comment mode and keeps the draft. Where `onClosesChange` is
 * given, "Comment and close" switches whether sending closes the item.
 */
export function ItemCommentModeHeader({
  label,
  title,
  item,
  excerpt,
  editing,
  closes = false,
  onClosesChange,
  onLeave,
}: {
  label: string;
  title: string;
  /** The item's definition, when the transcript has loaded it. */
  item: ItemLabelEntry | null;
  excerpt: string;
  editing: boolean;
  /** Whether sending closes the item with this comment. */
  closes?: boolean;
  /** Offered only on a stored item that is not closed. */
  onClosesChange?: (closes: boolean) => void;
  onLeave: () => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const definitionId = useId();
  const showDefinition = expanded && item !== null;
  return (
    <div
      data-testid="item-comment-mode"
      data-closes={closes || undefined}
      className={cn(
        "mx-3 mt-3 flex flex-col rounded-md border-l-2 bg-muted/40 text-sm",
        closes ? "border-l-success" : "border-l-warning",
      )}
    >
      <div className="flex items-start gap-2 px-2 py-1.5">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="flex min-w-0 items-baseline gap-1.5">
            <span className="shrink-0 text-muted-foreground">
              {editing ? "Editing comment on" : "Commenting on"}
            </span>
            <span className={LABEL_BADGE_CLASS}>{label}</span>
            {title && <span className="truncate font-medium">{title}</span>}
          </span>
          {!showDefinition && excerpt && (
            <span className="truncate text-muted-foreground">{excerpt}</span>
          )}
        </div>
        {onClosesChange && (
          <button
            type="button"
            aria-pressed={closes}
            aria-label="Comment and close"
            data-testid="item-comment-close-toggle"
            onClick={() => onClosesChange(!closes)}
            title={
              closes
                ? `Sending closes ${label} with this comment; tap to only comment`
                : `Close ${label} with this comment when it is sent`
            }
            className={cn(
              "flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs max-md:min-h-9",
              closes
                ? "border-success/40 bg-success/15 font-medium text-success"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            <CircleCheckIcon className="size-3.5" aria-hidden="true" />
            {/* Phones get the short label, leaving room for the item's title. */}
            <span className="max-sm:hidden">Comment and close</span>
            <span className="sm:hidden">Close</span>
          </button>
        )}
        {item !== null && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="mt-0.5 shrink-0 rounded-full text-muted-foreground hover:text-foreground max-md:-m-2 max-md:p-2"
            aria-expanded={expanded}
            aria-controls={showDefinition ? definitionId : undefined}
            aria-label={expanded ? `Collapse ${label} text` : `Show ${label} text`}
            title={expanded ? "Collapse to one line" : "Show the full item"}
          >
            {expanded ? (
              <ChevronUpIcon className="size-3.5" aria-hidden="true" />
            ) : (
              <ChevronDownIcon className="size-3.5" aria-hidden="true" />
            )}
          </button>
        )}
        <button
          type="button"
          onClick={onLeave}
          className="mt-0.5 shrink-0 rounded-full text-muted-foreground hover:text-foreground max-md:-m-2 max-md:p-2"
          aria-label="Leave comment mode"
          title="Leave comment mode (Esc); the draft is kept"
        >
          <XIcon className="size-3.5" />
        </button>
      </div>
      {showDefinition && (
        <div
          id={definitionId}
          role="region"
          aria-label={`${label} text`}
          data-testid="item-comment-mode-definition"
          className={cn(
            "overflow-y-auto overscroll-contain border-t border-border/60 px-2 py-1.5",
            DEFINITION_MAX_HEIGHT_CLASS,
          )}
        >
          <ItemLabelDefinition item={item} />
        </div>
      )}
    </div>
  );
}
