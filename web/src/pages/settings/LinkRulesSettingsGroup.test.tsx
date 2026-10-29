import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { authenticatedFetch } from "@/lib/identity";
import type { LinkRule } from "@/lib/linkRules";
import { LinkRulesSettingsGroup } from "./LinkRulesSettingsGroup";

vi.mock("@/lib/identity", () => ({
  authenticatedFetch: vi.fn(),
}));

const mockAuthenticatedFetch = vi.mocked(authenticatedFetch);

const GITHUB: LinkRule = { name: "GitHub", kind: "github", pattern: "", url: null, enabled: true };
const JIRA: LinkRule = {
  name: "Jira",
  kind: "url",
  pattern: "ABC-{num}",
  url: "https://jira.example.com/browse/ABC-{num}",
  enabled: false,
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
  } as unknown as Response;
}

function settings(rules: LinkRule[], { saved = false, version = 0, supported = true } = {}) {
  return { supported, saved, version, rules, defaults: [GITHUB, JIRA] };
}

/** Answer reads with `reads` in order (the last repeats) and PUTs with `writes`. */
function serve(reads: unknown[], writes: Response[] = []) {
  const puts: unknown[] = [];
  mockAuthenticatedFetch.mockImplementation(async (_path, init) => {
    if ((init as RequestInit | undefined)?.method === "PUT") {
      puts.push(JSON.parse(String((init as RequestInit).body)));
      const next = writes.shift();
      if (!next) throw new Error("unexpected PUT");
      return next;
    }
    return jsonResponse(reads.length > 1 ? reads.shift() : reads[0]);
  });
  return puts;
}

function renderGroup() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <TooltipProvider>
          <LinkRulesSettingsGroup />
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockAuthenticatedFetch.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("LinkRulesSettingsGroup", () => {
  it("lists the rules and previews them as the chat would", async () => {
    serve([settings([GITHUB, { ...JIRA, enabled: true }])]);
    renderGroup();
    expect(await screen.findByTestId("link-rule-0")).toBeTruthy();
    expect((screen.getByTestId("link-rule-1-pattern") as HTMLInputElement).value).toBe("ABC-{num}");
    const preview = screen.getByTestId("link-rules-preview");
    await waitFor(() =>
      expect(preview.querySelector("a")?.getAttribute("href")).toBe(
        "https://jira.example.com/browse/ABC-345",
      ),
    );
    // Code in the sample stays text.
    expect(preview.querySelector("code a")).toBe(null);
  });

  it("shows a rule's error and blocks saving until it is fixed", async () => {
    const puts = serve(
      [settings([GITHUB, JIRA])],
      [jsonResponse(settings([GITHUB, JIRA], { saved: true, version: 1 }))],
    );
    renderGroup();
    const url = (await screen.findByTestId("link-rule-1-url")) as HTMLInputElement;
    fireEvent.change(url, { target: { value: "javascript:alert(1)//{num}" } });
    expect(screen.getByTestId("link-rule-1-error").textContent).toContain("https://");
    expect((screen.getByTestId("link-rules-save") as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(url, { target: { value: "https://tracker.example.com/ABC-{num}" } });
    expect(screen.queryByTestId("link-rule-1-error")).toBe(null);
    fireEvent.click(screen.getByTestId("link-rules-save"));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({
      rules: [
        { name: "GitHub", kind: "github", enabled: true },
        {
          name: "Jira",
          kind: "url",
          enabled: false,
          pattern: "ABC-{num}",
          url: "https://tracker.example.com/ABC-{num}",
        },
      ],
      expected_version: 0,
    });
  });

  it("adds, toggles and deletes rules, and resets to the defaults", async () => {
    const puts = serve(
      [settings([JIRA], { saved: true, version: 3 })],
      [jsonResponse(settings([GITHUB, JIRA]))],
    );
    renderGroup();
    await screen.findByTestId("link-rule-0");
    fireEvent.click(screen.getByTestId("link-rules-add"));
    expect(screen.getByTestId("link-rule-1-error").textContent).toContain("pattern: required");
    fireEvent.click(screen.getByTestId("link-rule-1-delete"));
    fireEvent.click(screen.getByTestId("link-rules-add-github"));
    expect(screen.getByTestId("link-rule-1").textContent).toContain("Built in");
    fireEvent.click(screen.getByTestId("link-rule-0-enabled"));
    expect(screen.getByTestId("link-rules-add-session")).toBeTruthy();

    fireEvent.click(screen.getByTestId("link-rules-reset"));
    await waitFor(() => expect(puts).toEqual([{ rules: null, expected_version: 3 }]));
    await waitFor(() =>
      expect(screen.getByTestId("link-rule-0").textContent).toContain("Built in"),
    );
  });

  it("asks for a review when the rules changed elsewhere", async () => {
    serve(
      [
        settings([JIRA], { saved: true, version: 1 }),
        settings([GITHUB], { saved: true, version: 2 }),
      ],
      [jsonResponse({ detail: "The link rules changed since they were read" }, 409)],
    );
    renderGroup();
    fireEvent.click(await screen.findByTestId("link-rule-0-enabled"));
    fireEvent.click(screen.getByTestId("link-rules-save"));
    expect((await screen.findByRole("alert")).textContent).toContain("changed on another device");
  });

  it("keeps the defaults read-only without shared preferences", async () => {
    serve([settings([GITHUB, JIRA], { supported: false })]);
    renderGroup();
    expect((await screen.findByRole("note")).textContent).toContain("shared preferences");
    expect((screen.getByTestId("link-rules-add") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("link-rule-1-url") as HTMLInputElement).disabled).toBe(true);
  });
});
