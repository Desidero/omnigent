import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), "src", path), "utf8");
}

describe("extension slot host mounts", () => {
  it("keeps every public semantic slot mounted at its owning core surface", () => {
    expect(source("shell/ChatHeader.tsx")).toContain('slot="chat.header.actions"');
    expect(source("pages/ChatPage.tsx")).toContain('instance="chat-composer"');
    expect(source("shell/NewChatDialog.tsx")).toContain('instance="new-chat-composer"');
    expect(source("shell/WorkspacePanel.tsx")).toContain('slot="session.rightRail.tabs"');
    expect(source("shell/settingsNav.tsx")).toContain('slot="settings.sections"');
  });

  it("threads session, surface, and mobile navigation context at the host sites", () => {
    expect(source("shell/ChatHeader.tsx")).toContain("context={{ conversationId }}");
    expect(source("pages/ChatPage.tsx")).toContain("context={{ conversationId }}");
    expect(source("shell/WorkspacePanel.tsx")).toContain("context={{ conversationId }}");
    expect(source("shell/settingsNav.tsx")).toContain("onNavigate={onNavClick}");
  });
});
