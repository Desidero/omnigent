import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import {
  sandboxConnectionBlockMessage,
  type SandboxConnectionBlock,
} from "@/hooks/useSandboxConnectionBlocks";
import { sandboxOptionLabel } from "@/lib/capabilities";

/**
 * Under the host menu's sandbox rows: why a disabled provider is disabled.
 * When the user can fix it, the line is a menu item that opens the connect page.
 */
export function SandboxConnectionMenuNotices({
  blocks,
  onConnect,
}: {
  blocks: ReadonlyMap<string, SandboxConnectionBlock>;
  onConnect: () => void;
}) {
  return [...blocks].map(([provider, block]) => {
    const message = sandboxConnectionBlockMessage(sandboxOptionLabel(provider), block);
    return block.canConnect ? (
      <DropdownMenuItem
        key={provider}
        onSelect={onConnect}
        className="mobile-touch-target text-xs text-muted-foreground"
        data-testid={`new-chat-landing-sandbox-connect-${provider}`}
      >
        {message}
      </DropdownMenuItem>
    ) : (
      <div
        key={provider}
        className="px-2 py-1 text-xs leading-[18px] text-muted-foreground"
        data-testid={`new-chat-landing-sandbox-unavailable-${provider}`}
      >
        {message}
      </div>
    );
  });
}
