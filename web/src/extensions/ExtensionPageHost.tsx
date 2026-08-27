import type { ResolvedExtensionPage } from "./types";
import { useRefreshExtensions } from "./ExtensionProvider";
import { ExtensionViewHost } from "./ExtensionViewHost";
import { useExtensionHostServices } from "./services/useExtensionHostServices";

export function ExtensionPageHost({
  resolved,
  invocationContext,
}: {
  resolved: ResolvedExtensionPage;
  invocationContext?: Readonly<Record<string, string>>;
}) {
  const refresh = useRefreshExtensions();
  const { methods, events } = useExtensionHostServices(resolved.extension);
  return (
    <ExtensionViewHost
      extension={resolved.extension}
      page={resolved.page}
      refresh={refresh}
      methods={methods}
      events={events}
      invocationContext={invocationContext}
    />
  );
}
