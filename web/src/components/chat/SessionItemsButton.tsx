import { useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { BookmarkIcon, ExternalLinkIcon, LinkIcon } from "lucide-react";
import { ItemLabelPopover, itemLabelChipClass } from "@/components/blocks/ChatMarkdown";
import { OpenItemsPanel, trackedItems, useOpenItemCount } from "@/components/chat/OpenItemsPanel";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useIsMobileViewport } from "@/hooks/useIsMobileViewport";
import { useItemCommentRequest } from "@/lib/itemCommentDrafts";
import { ItemLabelIndexContext, ItemLabelSessionContext } from "@/lib/itemLabels";
import { MESSAGE_QUERY_PARAM } from "@/lib/messageDeepLink";
import { followLinkWithPopupFallback } from "@/lib/openLinkInApp";
import { useSearchParams } from "@/lib/routing";
import type { SessionLink } from "@/lib/sessionLinks";
import { cn } from "@/lib/utils";
import { MobileHeaderButton } from "@/shell/MobileHeaderButton";

const PANEL_NAME = "Open items and links";

function LinkRow({ link, sessionId }: { link: SessionLink; sessionId: string | null }) {
  return (
    <li className="flex min-w-0 items-center">
      {/* A pinned link's label previews where it was pinned, like any item. */}
      {link.item && (
        <ItemLabelPopover item={link.item}>
          <button
            type="button"
            aria-label={`Show link ${link.item.label}`}
            className={cn(itemLabelChipClass(false), "ml-3 shrink-0")}
          >
            {link.item.label}
          </button>
        </ItemLabelPopover>
      )}
      <a
        href={link.href}
        target="_blank"
        rel="noopener noreferrer"
        title={link.href}
        className="flex min-w-0 flex-1 items-center gap-2 px-3 py-1.5 text-ui hover:bg-muted"
        onClick={(event) => followLinkWithPopupFallback(event, link.href, sessionId ?? undefined)}
      >
        <span className="truncate">{link.title}</span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {new URL(link.href).hostname}
        </span>
        <ExternalLinkIcon
          className="ml-auto size-3 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
      </a>
    </li>
  );
}

/** The panel's two sections: the Open items tracker, then the session's links. */
function SessionItemsPanel({ links }: { links: readonly SessionLink[] }) {
  const sessionId = useContext(ItemLabelSessionContext);
  return (
    <>
      <OpenItemsPanel layout="section" />
      <section data-testid="session-links" aria-label="Links">
        <div className="flex items-center gap-2 px-3 py-2 text-ui font-medium">
          <LinkIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span>Links</span>
          <span className="opacity-70">({links.length})</span>
        </div>
        {links.length === 0 ? (
          <p className="px-3 pb-2 text-xs text-muted-foreground">
            Pages this session publishes, and links the agent pins with a label such as [L1], are
            listed here.
          </p>
        ) : (
          <ul className="max-h-[min(16rem,30vh)] overflow-y-auto border-t border-border py-1">
            {links.map((link) => (
              <LinkRow key={link.item?.label ?? link.key} link={link} sessionId={sessionId} />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

/**
 * The session header's button for the transcript's open items and links, with
 * the open count as a badge: a popover on desktop, a bottom sheet on phones.
 * Rendered by the transcript into `host`, the header's slot. Hidden until the
 * transcript has an item or a link.
 */
export function SessionItemsButton({
  host,
  links,
}: {
  host: HTMLElement;
  links: readonly SessionLink[];
}) {
  const index = useContext(ItemLabelIndexContext);
  const isMobile = useIsMobileViewport();
  const openCount = useOpenItemCount();
  const [open, setOpen] = useState(false);
  // "Show in conversation" in an item's preview jumps to a message: get out of its way.
  const [searchParams] = useSearchParams();
  const jumpTarget = searchParams.get(MESSAGE_QUERY_PARAM);
  useEffect(() => {
    if (jumpTarget) setOpen(false);
  }, [jumpTarget]);
  // So does "Comment", which moves to the composer.
  const commentRequest = useItemCommentRequest(useContext(ItemLabelSessionContext));
  useEffect(() => {
    if (commentRequest) setOpen(false);
  }, [commentRequest]);
  if (trackedItems(index).length === 0 && links.length === 0) return null;

  const trigger = (
    <MobileHeaderButton
      type="button"
      variant="ghost"
      size="icon-xs"
      glass={false}
      aria-label={openCount > 0 ? `${PANEL_NAME} (${openCount} open)` : PANEL_NAME}
      data-testid="session-items-trigger"
      className="border-none text-muted-foreground hover:text-foreground"
    >
      <span className="relative flex">
        <BookmarkIcon className="size-4 max-md:size-5" />
        {openCount > 0 && (
          <span
            data-testid="session-items-count"
            aria-hidden="true"
            className="absolute -top-1.5 -right-2 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-primary px-0.5 text-[10px] leading-none font-medium text-primary-foreground tabular-nums"
          >
            {openCount > 99 ? "99+" : openCount}
          </span>
        )}
      </span>
    </MobileHeaderButton>
  );

  if (isMobile) {
    return createPortal(
      // Not modal, so an item's preview can hand focus to the page behind, which closes the sheet.
      <Dialog open={open} onOpenChange={setOpen} modal={false}>
        <DialogTrigger asChild>{trigger}</DialogTrigger>
        {/* Docked to the bottom edge as a sheet; the inline top beats the iOS shell's centering. */}
        <DialogContent
          data-testid="session-items-panel"
          aria-describedby={undefined}
          className="top-auto bottom-0 max-h-[80dvh] max-w-full translate-y-0 gap-2 overflow-y-auto rounded-b-none px-2 pt-4 pb-[calc(1rem+var(--omnigent-safe-bottom,0px))] sm:max-w-full"
          style={{ top: "auto" }}
        >
          <DialogTitle className="px-3">{PANEL_NAME}</DialogTitle>
          <SessionItemsPanel links={links} />
        </DialogContent>
      </Dialog>,
      host,
    );
  }
  return createPortal(
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>Open items &amp; links</TooltipContent>
      </Tooltip>
      <PopoverContent
        align="end"
        aria-label={PANEL_NAME}
        data-testid="session-items-panel"
        className="menu-surface max-h-[var(--radix-popover-content-available-height)] w-96 max-w-[calc(100vw-1rem)] gap-1 overflow-y-auto rounded-[12px] p-1.5 ring-0"
      >
        <SessionItemsPanel links={links} />
      </PopoverContent>
    </Popover>,
    host,
  );
}
