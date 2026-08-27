import { useMemo } from "react";
import { Spinner } from "@/components/ui/spinner";
import { useLocation, useParams } from "@/lib/routing";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { resolveExtensionPage } from "./catalog";
import { useExtensions, useExtensionsLoading } from "./ExtensionProvider";
import { ExtensionPageHost } from "./ExtensionPageHost";

export function ExtensionPageRoute() {
  const params = useParams<{ extensionId: string; "*": string }>();
  const location = useLocation();
  const route = params["*"]?.split("/")[0];
  const extensions = useExtensions();
  const extensionsLoading = useExtensionsLoading();
  const resolved = resolveExtensionPage(extensions, params.extensionId, route);

  const invocationContext = useMemo<Readonly<Record<string, string>>>(() => {
    const context: Record<string, string> = {};
    const conversationId = new URLSearchParams(location.search).get("conversationId");
    if (conversationId) context.conversationId = conversationId;
    return context;
  }, [location.search]);

  if (extensionsLoading) {
    return (
      <div className="flex h-full min-h-0 w-full flex-col overflow-hidden pt-14 md:pt-12">
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <Spinner className="size-5 text-muted-foreground" aria-label="Loading extension" />
        </div>
      </div>
    );
  }

  if (!resolved) return <NotFoundPage />;

  return <ExtensionPageHost resolved={resolved} invocationContext={invocationContext} />;
}
