import { NetworkIcon } from "lucide-react";
import { subagentRoutingReach } from "@/components/CostRoutingControl";
import { useSessionField } from "@/components/composer/sessionPickerInputs";
import { DropdownMenuCheckboxItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { useSession } from "@/hooks/useSession";
import { SUBAGENT_ROUTING_LABEL } from "@/lib/agentLabels";
import { useServerInfo } from "@/lib/CapabilitiesContext";

interface SubagentRoutingItemProps {
  /** Read and change this session instead of the active conversation. */
  sessionId: string | undefined;
  /** The conversation the picker is showing, or `null` before one exists. */
  conversationId: string | null;
  disabled: boolean;
  /** Persist the switch; the picker runs it under its busy guard. */
  onChange: (mode: "on" | "off") => void;
}

/**
 * The session picker's "Route sub-agents" row: Smart Routing picks the model
 * of each sub-agent the session starts while the session keeps its own.
 * Renders nothing on a server that cannot route or a session with no control.
 */
export function SubagentRoutingItem(props: SubagentRoutingItemProps) {
  const serverInfo = useServerInfo();
  if (serverInfo === "loading" || !serverInfo.smart_routing_enabled) return null;
  if (props.conversationId === null) return null;
  return <RoutableSubagentRoutingItem {...props} conversationId={props.conversationId} />;
}

function RoutableSubagentRoutingItem({
  sessionId,
  conversationId,
  disabled,
  onChange,
}: SubagentRoutingItemProps & { conversationId: string }) {
  const { session } = useSession(conversationId);
  const override = useSessionField(sessionId, (state) => state.subagentRoutingOverride);
  // The store holds the live switch; the snapshot's can trail a toggle.
  const costControlModeOverride = useSessionField(
    sessionId,
    (state) => state.costControlModeOverride,
  );
  const reach =
    session === null
      ? null
      : subagentRoutingReach({ ...session, costControlModeOverride }, override);
  if (reach === null) return null;
  return (
    <>
      <DropdownMenuCheckboxItem
        checked={override === "on"}
        disabled={disabled}
        onCheckedChange={(checked) => onChange(checked ? "on" : "off")}
        onSelect={(event) => event.preventDefault()}
        className="items-start"
        data-testid="composer-agent-subagent-routing"
        data-subagent-routing-reach={reach}
      >
        <NetworkIcon className="mt-0.5 size-4" aria-hidden="true" />
        <span className="flex min-w-0 flex-col">
          <span>{SUBAGENT_ROUTING_LABEL}</span>
          {reach === "child-sessions" && (
            <span className="text-xs whitespace-normal text-muted-foreground">
              Child sessions only. This session started without sub-agent routing, so its built-in
              sub-agents keep their own model.
            </span>
          )}
        </span>
      </DropdownMenuCheckboxItem>
      <DropdownMenuSeparator />
    </>
  );
}
