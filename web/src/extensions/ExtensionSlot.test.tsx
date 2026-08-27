import { fireEvent, render, screen } from "@testing-library/react";
import type { MouseEvent } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ExtensionCatalogProvider } from "./ExtensionProvider";
import { ExtensionSlot, ExtensionSlotHost } from "./ExtensionSlot";
import type { ExtensionCatalogItem, ExtensionSlotId } from "./types";

const page = { id: "acme.review.page", title: "Review", route: "review", view: "review" };
const extension: ExtensionCatalogItem = {
  object: "extension",
  id: "acme.review",
  display_name: "Review",
  distribution: "acme-review",
  version: "1.0.0",
  extension_api: 1,
  status: "enabled",
  permissions: [],
  pages: [page],
  primary_navigation: [],
  slot_items: [
    {
      id: "acme.review.header",
      slot: "chat.header.actions",
      kind: "action",
      label: "Header review",
      page: page.id,
      icon: "search",
      order: 500,
      when: null,
    },
    {
      id: "acme.review.composer",
      slot: "composer.actions",
      kind: "action",
      label: "Composer review",
      page: page.id,
      icon: null,
      order: 500,
      when: null,
    },
    {
      id: "acme.review.rail",
      slot: "session.rightRail.tabs",
      kind: "tab",
      label: "Rail review",
      page: page.id,
      icon: "dashboard",
      order: 500,
      when: null,
    },
    {
      id: "acme.review.settings",
      slot: "settings.sections",
      kind: "section",
      label: "Review settings",
      page: page.id,
      icon: "unknown",
      order: 500,
      when: null,
    },
  ],
  browser: {
    declared: true,
    has_styles: false,
    digest: "digest",
    script_url: "/script",
    style_url: null,
  },
};

function renderSlot(
  slot: ExtensionSlotId,
  options: {
    initialEntry?: string;
    conversationId?: string;
    instance?: string;
    onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
  } = {},
) {
  return render(
    <ExtensionCatalogProvider extensions={[extension]}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[options.initialEntry ?? "/"]}>
          <ExtensionSlot
            slot={slot}
            context={{ conversationId: options.conversationId }}
            instance={options.instance}
            onNavigate={options.onNavigate}
          />
        </MemoryRouter>
      </TooltipProvider>
    </ExtensionCatalogProvider>,
  );
}

describe("ExtensionSlot", () => {
  it("leaves core children untouched for an empty catalog", () => {
    const { container } = render(
      <ExtensionCatalogProvider extensions={[]}>
        <MemoryRouter>
          <ExtensionSlotHost slot="composer.actions">
            <button type="button">Core action</button>
          </ExtensionSlotHost>
        </MemoryRouter>
      </ExtensionCatalogProvider>,
    );

    expect(container.innerHTML).toBe('<button type="button">Core action</button>');
  });

  it.each([
    ["chat.header.actions", "acme.review.header", "/extensions/acme.review/review"],
    ["composer.actions", "acme.review.composer", "/extensions/acme.review/review"],
    ["session.rightRail.tabs", "acme.review.rail", "/extensions/acme.review/review"],
    ["settings.sections", "acme.review.settings", "/settings/extensions/acme.review/review"],
  ] as const)("renders a core-owned link in %s", (slot, id, href) => {
    renderSlot(slot);
    const link = screen.getByTestId(`extension-slot-${id}`);
    expect(link).toHaveAttribute("href", href);
    expect(link.querySelector("svg")).not.toBeNull();
    if (slot === "session.rightRail.tabs") expect(link).not.toHaveAttribute("role", "tab");
  });

  it("passes session context and uses surface-specific identifiers", () => {
    renderSlot("composer.actions", { conversationId: "conv_123", instance: "chat" });
    expect(screen.getByTestId("extension-slot-chat-acme.review.composer")).toHaveAttribute(
      "href",
      "/extensions/acme.review/review?conversationId=conv_123",
    );
  });

  it("marks active settings links and forwards mobile navigation", () => {
    const onNavigate = vi.fn();
    renderSlot("settings.sections", {
      initialEntry: "/settings/extensions/acme.review/review",
      onNavigate,
    });
    const link = screen.getByTestId("extension-slot-acme.review.settings");
    expect(link).toHaveAttribute("aria-current", "page");
    fireEvent.click(link);
    expect(onNavigate).toHaveBeenCalledOnce();
  });
});
