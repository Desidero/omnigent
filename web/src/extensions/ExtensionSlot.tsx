import type { MouseEvent, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Link, useLocation } from "@/lib/routing";
import { cn } from "@/lib/utils";
import { SIDEBAR_ROW } from "@/shell/sidebarStyles";
import { useExtensions } from "./ExtensionProvider";
import { extensionIcon } from "./icons";
import { resolveExtensionPageFromPath } from "./catalog";
import { useSessionPublishedFields } from "./publishedFields";
import { publishedFieldText, resolveSlotItems, type ResolvedSlotItem } from "./slots";
import type { ExtensionSlotId, PublishedFields } from "./types";

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

export function ExtensionSlot(props: ExtensionSlotProps) {
  const entries = resolveSlotItems(useExtensions(), props.slot);
  // An empty slot stays dormant: no routing hooks, nothing rendered.
  if (entries.length === 0) return null;
  return <ExtensionSlotLinks {...props} entries={entries} />;
}

type SlotLinksProps = ExtensionSlotProps & { entries: ResolvedSlotItem[] };

function ExtensionSlotLinks(props: SlotLinksProps) {
  // Only session actions that show a published field cost a session read.
  const labelled =
    (props.slot === "chat.header.actions" || props.slot === "composer.actions") &&
    Boolean(props.context?.conversationId) &&
    props.entries.some(({ item }) => item.label_field);
  return labelled ? (
    <LabelledSlotLinks {...props} />
  ) : (
    <SlotLinkList {...props} publishedFields={null} />
  );
}

function LabelledSlotLinks(props: SlotLinksProps) {
  const publishedFields = useSessionPublishedFields(props.context?.conversationId);
  return <SlotLinkList {...props} publishedFields={publishedFields ?? null} />;
}

function SlotLinkList({
  slot,
  onNavigate,
  context,
  instance,
  entries,
  publishedFields,
}: SlotLinksProps & { publishedFields: PublishedFields | null }) {
  const extensions = useExtensions();
  const location = useLocation();
  const activePageId = resolveExtensionPageFromPath(extensions, location.pathname)?.page.id;
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
    const fieldLabel = item.label_field
      ? publishedFieldText(publishedFields, extension.id, item.label_field)
      : null;
    const header = slot === "chat.header.actions";
    return (
      <Tooltip key={item.id}>
        <TooltipTrigger asChild>
          {/* Match the neighbouring core controls: header icons or the composer mic. */}
          <Button
            asChild
            variant="ghost"
            size={fieldLabel ? (header ? "xs" : "sm") : header ? "icon-xs" : "icon"}
            className={cn(
              header
                ? "border-none text-muted-foreground hover:text-foreground"
                : "size-8 md:size-7",
              fieldLabel && "size-auto h-6 max-w-48 text-muted-foreground hover:text-foreground",
              fieldLabel && !header && "h-8 md:h-7",
            )}
          >
            <Link
              to={to}
              onClick={onNavigate}
              aria-label={fieldLabel ? `${item.label}: ${fieldLabel}` : item.label}
              aria-current={active ? "page" : undefined}
              data-testid={testId}
              componentId={`extension.slot.${instance ? `${instance}.` : ""}${item.id}`}
            >
              <Icon className="size-4" />
              {/* Extension text, rendered as text. */}
              {fieldLabel && <span className="truncate">{fieldLabel}</span>}
            </Link>
          </Button>
        </TooltipTrigger>
        <TooltipContent>{item.label}</TooltipContent>
      </Tooltip>
    );
  });
}
