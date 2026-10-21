import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronDownIcon, MessageSquareDotIcon, XIcon } from "lucide-react";
import {
  ItemLabelChipMarks,
  ItemLabelPopover,
  itemLabelChipClass,
  itemLabelChipName,
} from "@/components/blocks/ChatMarkdown";
import { useSession } from "@/hooks/useSession";
import { useUpdateSessionLabels } from "@/hooks/useSessionLabels";
import {
  DISMISSED_ITEMS_LABEL_KEY,
  ItemLabelIndexContext,
  ItemLabelSessionContext,
  decodeDismissedItems,
  encodeDismissedItems,
  itemLabelTitle,
  mentionedInLatestReply,
  type ItemLabelEntry,
} from "@/lib/itemLabels";
import { revealItemCommentTray, useItemCommentDraftCounts } from "@/lib/itemCommentDrafts";
import { cn } from "@/lib/utils";

// Header chips shown before the row has been measured (or without layout).
const UNMEASURED_CHIP_LIMIT = 6;

/**
 * How many chips of `chipWidths` fit in `available` pixels, `gap` apart,
 * leaving room for an `overflowWidth` "+N" count whenever some are left out.
 */
export function fitItemChipCount(
  chipWidths: readonly number[],
  available: number,
  gap: number,
  overflowWidth: number,
): number {
  let used = 0;
  for (const [index, width] of chipWidths.entries()) {
    used += (index > 0 ? gap : 0) + width;
    const leftOut = index < chipWidths.length - 1;
    if (used + (leftOut ? gap + overflowWidth : 0) > available) return index;
  }
  return chipWidths.length;
}

/**
 * Fits the header chips to the row's width: `measureRef` holds an invisible
 * copy of every chip then the "+N" count, which `rowRef` is sized against.
 * Null until measured, and in environments without layout.
 */
function useFittedChipCount(chipKey: string) {
  const rowRef = useRef<HTMLSpanElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const [count, setCount] = useState<number | null>(null);
  useLayoutEffect(() => {
    const row = rowRef.current;
    const measure = measureRef.current;
    if (!row || !measure || typeof ResizeObserver === "undefined") return;
    const update = () => {
      if (row.clientWidth === 0) return;
      const widths = [...measure.children].map((child) => child.getBoundingClientRect().width);
      const overflowWidth = widths.pop() ?? 0;
      const gap = Number.parseFloat(getComputedStyle(row).columnGap) || 0;
      setCount(fitItemChipCount(widths, row.clientWidth, gap, overflowWidth));
    };
    update();
    // The row is flex-1 with a zero basis, so showing fewer chips never resizes it.
    const observer = new ResizeObserver(update);
    observer.observe(row);
    observer.observe(measure);
    return () => observer.disconnect();
  }, [chipKey]);
  return { rowRef, measureRef, count };
}

/**
 * Collapses an expanded `<details>` when the user presses outside it. Presses
 * inside a popover don't count, since the panel's chips open popovers.
 */
export function useCollapseOnOutsidePress() {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const details = detailsRef.current;
      const target = event.target as Element | null;
      if (!details?.open || !target || details.contains(target)) return;
      if (target.closest("[data-slot=popover-content]")) return;
      details.open = false;
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);
  return detailsRef;
}

/**
 * The open items the user dismissed from this session's tracker, read from and
 * written to the session's labels so they stay dismissed on every device. A
 * write in flight shows its own value so a dismiss takes effect at once.
 */
function useDismissedItems(sessionId: string | null) {
  const { session } = useSession(sessionId);
  const update = useUpdateSessionLabels(sessionId);
  const pending = update.isPending ? update.variables?.[DISMISSED_ITEMS_LABEL_KEY] : undefined;
  const stored = session?.labels?.[DISMISSED_ITEMS_LABEL_KEY];
  const dismissed = useMemo(
    () => decodeDismissedItems(pending !== undefined ? pending : stored),
    [pending, stored],
  );
  const write = (labels: Iterable<string>) =>
    update.mutate({ [DISMISSED_ITEMS_LABEL_KEY]: encodeDismissedItems(labels) });
  return {
    dismissed,
    dismiss: (label: string) => write([...dismissed, label]),
    restore: (label: string) => write([...dismissed].filter((other) => other !== label)),
  };
}

function ItemRow({
  item,
  draftCount,
  recent,
  onDismiss,
  onRestore,
}: {
  item: ItemLabelEntry;
  draftCount: number;
  recent: boolean;
  onDismiss?: () => void;
  onRestore?: () => void;
}) {
  const closed = item.closedBy !== null;
  const title = useMemo(() => itemLabelTitle(item.source.text, item.label), [item]);
  return (
    <div className="flex min-w-0 items-center">
      <ItemLabelPopover item={item}>
        <button
          type="button"
          aria-label={itemLabelChipName(
            item.label,
            closed,
            item.comments.length,
            draftCount,
            recent,
          )}
          className="flex min-w-0 flex-1 items-baseline gap-2 px-3 py-1.5 text-left text-ui hover:bg-muted"
        >
          <span className={cn(itemLabelChipClass(closed, recent), "shrink-0")}>
            {item.label}
            <ItemLabelChipMarks commentCount={item.comments.length} draftCount={draftCount} />
          </span>
          <span className={cn("truncate", closed && "text-muted-foreground line-through")}>
            {title}
          </span>
        </button>
      </ItemLabelPopover>
      {onDismiss && (
        <button
          type="button"
          aria-label={`Dismiss item ${item.label}`}
          title="Dismiss from open items"
          className="mr-2 shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={onDismiss}
        >
          <XIcon className="size-3" aria-hidden="true" />
        </button>
      )}
      {onRestore && (
        <button
          type="button"
          aria-label={`Restore item ${item.label}`}
          className="mr-2 shrink-0 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={onRestore}
        >
          Restore
        </button>
      )}
    </div>
  );
}

/**
 * Collapsible "Open items" tracker pinned above the chat thread, beside the
 * Plan tracker. The header lists open item labels as chips, plus a jump to the
 * comment drafts when there are any; expanding lists every item with its
 * title, closed ones last. Items the latest reply mentions come first, tinted,
 * one it just closed among them struck through. An open item can be dismissed
 * from the tracker (per session, on every device) and restored from the
 * "dismissed" list at the bottom. Self-hides until the transcript uses item
 * labels.
 */
export function OpenItemsPanel({ className }: { className?: string }) {
  const index = useContext(ItemLabelIndexContext);
  const sessionId = useContext(ItemLabelSessionContext);
  const draftCounts = useItemCommentDraftCounts(sessionId);
  const { dismissed, dismiss, restore } = useDismissedItems(sessionId);
  const [showDismissed, setShowDismissed] = useState(false);
  const allItems = useMemo(() => (index?.enabled ? [...index.items.values()] : []), [index]);
  // A dismissal hides an open item; closing it later lists it as closed as usual.
  const isDismissed = (item: ItemLabelEntry) => item.closedBy === null && dismissed.has(item.label);
  const items = allItems.filter((item) => !isDismissed(item));
  const dismissedItems = allItems.filter(isDismissed);
  const isRecent = (item: ItemLabelEntry) => index !== null && mentionedInLatestReply(index, item);
  const recent = items.filter(isRecent);
  const open = items.filter((item) => item.closedBy === null);
  const otherOpen = open.filter((item) => !isRecent(item));
  const closed = items.filter((item) => item.closedBy !== null && !isRecent(item));
  const chips = [...recent, ...otherOpen];
  const chipKey = chips
    .map(
      (item) =>
        `${item.label}:${isRecent(item) ? "r" : ""}${item.closedBy ? "c" : ""}:${item.comments.length}:${draftCounts.get(item.label) ?? 0}`,
    )
    .join(" ");
  const fit = useFittedChipCount(chipKey);
  const detailsRef = useCollapseOnOutsidePress();
  if (allItems.length === 0) return null;
  const headerChips = chips.slice(0, fit.count ?? UNMEASURED_CHIP_LIMIT);
  const draftTotal = [...draftCounts.values()].reduce((total, count) => total + count, 0);

  return (
    <div className={cn("shrink-0 px-3 md:px-4", className)}>
      <details
        ref={detailsRef}
        data-testid="open-items"
        className="group mx-auto mb-1 max-w-3xl overflow-hidden rounded-xl border border-border bg-card shadow-sm"
      >
        <summary className="relative flex cursor-pointer list-none select-none items-center gap-2 px-3 py-2 text-ui font-medium [&::-webkit-details-marker]:hidden">
          <MessageSquareDotIcon className="size-4 shrink-0 text-muted-foreground" />
          <span className="shrink-0">Open items</span>
          <span className="shrink-0 opacity-70">({open.length})</span>
          {/* Chips open their popover; keep their clicks from toggling the panel. */}
          <span
            ref={fit.rowRef}
            className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden font-normal"
            onClick={(event) => {
              if ((event.target as Element).closest("button")) event.preventDefault();
            }}
          >
            {headerChips.map((item) => {
              const draftCount = draftCounts.get(item.label) ?? 0;
              const recentChip = isRecent(item);
              return (
                <ItemLabelPopover key={item.label} item={item} openOnHover>
                  <button
                    type="button"
                    aria-label={itemLabelChipName(
                      item.label,
                      item.closedBy !== null,
                      item.comments.length,
                      draftCount,
                      recentChip,
                    )}
                    className={cn(
                      itemLabelChipClass(item.closedBy !== null, recentChip),
                      "shrink-0",
                    )}
                  >
                    {item.label}
                    <ItemLabelChipMarks
                      commentCount={item.comments.length}
                      draftCount={draftCount}
                    />
                  </button>
                </ItemLabelPopover>
              );
            })}
            {chips.length > headerChips.length && (
              <span className="shrink-0 text-xs text-muted-foreground">
                +{chips.length - headerChips.length}
              </span>
            )}
          </span>
          <span
            ref={fit.measureRef}
            aria-hidden="true"
            className="pointer-events-none invisible absolute top-0 left-0 flex gap-1 font-normal whitespace-nowrap"
          >
            {chips.map((item) => (
              <span
                key={item.label}
                className={itemLabelChipClass(item.closedBy !== null, isRecent(item))}
              >
                {item.label}
                <ItemLabelChipMarks
                  commentCount={item.comments.length}
                  draftCount={draftCounts.get(item.label) ?? 0}
                />
              </span>
            ))}
            <span className="text-xs">+{chips.length}</span>
          </span>
          {draftTotal > 0 && (
            <button
              type="button"
              className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border px-2 text-xs font-normal text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={(event) => {
                event.preventDefault();
                revealItemCommentTray();
              }}
            >
              <span aria-hidden="true" className="size-1.5 rounded-full bg-warning" />
              {draftTotal} draft{draftTotal === 1 ? "" : "s"}
            </button>
          )}
          <ChevronDownIcon className="size-4 shrink-0 transition-transform group-open:rotate-180" />
        </summary>
        {/* Capped like the Plan tracker so a long list can't swallow the chat. */}
        <div className="max-h-[180px] overflow-y-auto border-t border-border py-1">
          {recent.length > 0 && (
            <div className="px-3 pt-1 pb-1 text-xs text-muted-foreground">In the latest reply</div>
          )}
          {recent.map((item) => (
            <ItemRow
              key={item.label}
              item={item}
              draftCount={draftCounts.get(item.label) ?? 0}
              recent
              onDismiss={item.closedBy === null ? () => dismiss(item.label) : undefined}
            />
          ))}
          {recent.length > 0 && otherOpen.length > 0 && (
            <div className="px-3 pt-2 pb-1 text-xs text-muted-foreground">
              Other open ({otherOpen.length})
            </div>
          )}
          {otherOpen.map((item) => (
            <ItemRow
              key={item.label}
              item={item}
              draftCount={draftCounts.get(item.label) ?? 0}
              recent={false}
              onDismiss={() => dismiss(item.label)}
            />
          ))}
          {closed.length > 0 && (
            <div className="px-3 pt-2 pb-1 text-xs text-muted-foreground">
              Closed ({closed.length})
            </div>
          )}
          {closed.map((item) => (
            <ItemRow
              key={item.label}
              item={item}
              draftCount={draftCounts.get(item.label) ?? 0}
              recent={false}
            />
          ))}
          {dismissedItems.length > 0 && (
            <button
              type="button"
              className="w-full px-3 pt-2 pb-1 text-left text-xs text-muted-foreground hover:text-foreground"
              aria-expanded={showDismissed}
              onClick={() => setShowDismissed((shown) => !shown)}
            >
              {showDismissed ? "Hide" : "Show"} dismissed ({dismissedItems.length})
            </button>
          )}
          {showDismissed &&
            dismissedItems.map((item) => (
              <ItemRow
                key={item.label}
                item={item}
                draftCount={draftCounts.get(item.label) ?? 0}
                recent={false}
                onRestore={() => restore(item.label)}
              />
            ))}
        </div>
      </details>
    </div>
  );
}
