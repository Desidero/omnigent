import { useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { BookmarkIcon } from "lucide-react";
import { OpenItemsPanel, trackedItems, useOpenItemCount } from "@/components/chat/OpenItemsPanel";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useIsMobileViewport } from "@/hooks/useIsMobileViewport";
import { ItemLabelIndexContext } from "@/lib/itemLabels";
import { MESSAGE_QUERY_PARAM } from "@/lib/messageDeepLink";
import { useSearchParams } from "@/lib/routing";
import { MobileHeaderButton } from "@/shell/MobileHeaderButton";

const PANEL_NAME = "Open items";

/**
 * The session header's button for the transcript's open items, with the open
 * count as a badge: a popover on desktop, a bottom sheet on phones. Rendered
 * by the transcript into `host`, the header's slot. Hidden until the
 * transcript uses item labels.
 */
export function SessionItemsButton({ host }: { host: HTMLElement }) {
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
  if (trackedItems(index).length === 0) return null;

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
          <OpenItemsPanel layout="section" />
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
        <TooltipContent>{PANEL_NAME}</TooltipContent>
      </Tooltip>
      <PopoverContent
        align="end"
        aria-label={PANEL_NAME}
        data-testid="session-items-panel"
        className="menu-surface max-h-[var(--radix-popover-content-available-height)] w-96 max-w-[calc(100vw-1rem)] gap-1 overflow-y-auto rounded-[12px] p-1.5 ring-0"
      >
        <OpenItemsPanel layout="section" />
      </PopoverContent>
    </Popover>,
    host,
  );
}
