import type { ReactNode } from "react";
import { ItemLabelMessageContext } from "@/lib/itemLabels";
import type { OpenItemReply, StoredOpenItem } from "@/lib/openItems";
import { relativeTime } from "@/lib/relativeTime";

function ago(epochSeconds: number): string {
  const age = relativeTime(epochSeconds * 1000);
  return age === "now" ? "just now" : `${age} ago`;
}

function replyAuthor(reply: OpenItemReply): string {
  return reply.author === "agent" ? "Agent" : (reply.by ?? "You");
}

/**
 * A stored item's thread as the store holds it: each comment and reply once,
 * in order, then how it was closed. The resolution is left out when it only
 * repeats the last reply. `messageId` resolves labels inside the text, which
 * `markdown` renders (the chat's renderer, passed in by its callers).
 */
export function StoredItemThread({
  item,
  messageId,
  markdown,
}: {
  item: StoredOpenItem;
  messageId: string | null;
  markdown: (text: string) => ReactNode;
}) {
  const last = item.replies.at(-1)?.text.trim();
  const resolution = item.resolution?.trim();
  return (
    <ItemLabelMessageContext.Provider value={messageId}>
      {item.replies.length > 0 && (
        <section aria-label="Thread" className="flex flex-col gap-1.5">
          {item.replies.map((reply) => (
            <div
              key={`${reply.at}:${reply.author}:${reply.text.slice(0, 40)}`}
              data-testid="open-item-reply"
              data-author={reply.author}
              className="border-l-2 border-border pl-2"
            >
              <div className="text-xs text-muted-foreground">
                {`${replyAuthor(reply)} · ${ago(reply.at)}`}
              </div>
              {markdown(reply.text)}
            </div>
          ))}
        </section>
      )}
      {item.status === "closed" && (
        <div data-testid="open-item-resolution" className="border-l-2 border-border pl-2">
          <div className="text-xs text-muted-foreground">
            {`Closed by ${item.closed_by === "user" ? "a person" : "the agent"}`}
            {item.closed_at !== null && ` · ${ago(item.closed_at)}`}
          </div>
          {resolution && resolution !== last && <p className="whitespace-pre-wrap">{resolution}</p>}
        </div>
      )}
    </ItemLabelMessageContext.Provider>
  );
}
