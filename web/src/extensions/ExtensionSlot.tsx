import type { MouseEvent, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Link, useLocation } from "@/lib/routing";
import { cn } from "@/lib/utils";
import { SIDEBAR_ROW } from "@/shell/sidebarStyles";
import { useExtensions } from "./ExtensionProvider";
import { extensionIcon } from "./icons";
import { resolveExtensionPageFromPath } from "./catalog";
import { resolveSlotItems } from "./slots";
import type { ExtensionSlotId } from "./types";

export interface ExtensionSlotProps {
  slot: ExtensionSlotId;
  context?: { conversationId?: string | null };
  instance?: string;
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
}

export function ExtensionSlotHost({
  children,
  ...slotProps
}: ExtensionSlotProps & { children: ReactNode }) {
  return (
    <>
      {children}
      <ExtensionSlot {...slotProps} />
    </>
  );
}

export function ExtensionSlot({ slot, context, instance, onNavigate }: ExtensionSlotProps) {
  const extensions = useExtensions();
  const location = useLocation();
  const activePageId = resolveExtensionPageFromPath(extensions, location.pathname)?.page.id;
  const entries = resolveSlotItems(extensions, slot);
  return entries.map(({ extension, item, page }) => {
    const Icon = extensionIcon(item.icon);
    const basePath =
      slot === "settings.sections"
        ? `/settings/extensions/${extension.id}/${page.route}`
        : `/extensions/${extension.id}/${page.route}`;
    const search = new URLSearchParams();
    if (context?.conversationId) search.set("conversationId", context.conversationId);
    const to = search.size > 0 ? `${basePath}?${search}` : basePath;
    const active = activePageId === page.id;
    const idPrefix = instance ? `${instance}-` : "";
    const testId = `extension-slot-${idPrefix}${item.id}`;
    if (slot === "settings.sections") {
      return (
        <Button
          key={item.id}
          asChild
          variant="ghost"
          className={cn(
            SIDEBAR_ROW,
            "w-full justify-start border-0 font-normal",
            active &&
              "bg-[var(--sidebar-active)] text-[var(--sidebar-active-foreground)] hover:bg-[var(--sidebar-active)]",
          )}
        >
          <Link
            to={to}
            onClick={onNavigate}
            data-testid={testId}
            componentId={`settings.extension.${item.id}`}
            aria-current={active ? "page" : undefined}
          >
            <Icon
              className={cn(
                "ui-icon",
                active ? "text-[var(--sidebar-active-foreground)]" : "text-muted-foreground",
              )}
            />
            {item.label}
          </Link>
        </Button>
      );
    }
    if (slot === "session.rightRail.tabs") {
      return (
        <Tooltip key={item.id}>
          <TooltipTrigger asChild>
            <Link
              to={to}
              aria-label={item.label}
              aria-current={active ? "page" : undefined}
              data-testid={testId}
              componentId={`chat.right_rail.extension.${item.id}`}
              className={cn(
                "inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground",
                active && "bg-muted text-foreground",
              )}
            >
              <Icon className="size-4" />
            </Link>
          </TooltipTrigger>
          <TooltipContent>{item.label}</TooltipContent>
        </Tooltip>
      );
    }
    return (
      <Tooltip key={item.id}>
        <TooltipTrigger asChild>
          <Button asChild variant="ghost" size="icon" className="size-9 md:size-8">
            <Link
              to={to}
              onClick={onNavigate}
              aria-label={item.label}
              aria-current={active ? "page" : undefined}
              data-testid={testId}
              componentId={`extension.slot.${instance ? `${instance}.` : ""}${item.id}`}
            >
              <Icon className="size-4" />
            </Link>
          </Button>
        </TooltipTrigger>
        <TooltipContent>{item.label}</TooltipContent>
      </Tooltip>
    );
  });
}
