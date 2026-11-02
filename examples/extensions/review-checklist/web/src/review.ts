import type {
  ExtensionContext,
  ExtensionProjectSummary,
  ExtensionPullRequest,
  ExtensionSessionSummary,
} from "@omnigent/extension-sdk";
import { button, confirmInline, el, errorMessage, renderKeepingFocus } from "./dom";
import {
  allTemplates,
  checkedCount,
  chooseTemplate,
  itemsOf,
  relativeTime,
  resolveTemplate,
  setChecked,
  SOURCE_LABELS,
  templateChangedSinceTicks,
  uncheckAll,
} from "./model";
import {
  BROWSER_ONLY_NOTICE,
  type ChecklistData,
  ChecklistStore,
  type SaveState,
  saveStateText,
  UNAVAILABLE_NOTICE,
} from "./store";

type Session = ExtensionSessionSummary;
type PullRequestState =
  | { kind: "loading" }
  | { kind: "done"; pr: ExtensionPullRequest | null }
  | { kind: "error"; message: string };

const STATUS: Record<Session["status"], { label: string; icon: string }> = {
  idle: { label: "Idle", icon: "○" },
  running: { label: "Running", icon: "◔" },
  waiting: { label: "Waiting for you", icon: "?" },
  failed: { label: "Failed", icon: "✕" },
};

export function bannerFor(session: Session): string | null {
  if (session.status === "running") {
    return "The agent is still working. The work may change before it finishes.";
  }
  if (session.status === "waiting") return "The agent is waiting for you: a question or an approval.";
  if (session.status === "failed") {
    return "The last turn failed. Check the error in the session before reviewing.";
  }
  if (session.unread) return "There's a finished turn you haven't read yet.";
  return null;
}

/** The SDK has no get-by-id: try the shell's cache, then walk the authoritative list. */
export async function findSession(context: ExtensionContext, sessionId: string): Promise<Session | null> {
  const cached = await context.sessions.getCached({ limit: 1000 }).catch(() => null);
  const hit = cached?.find((session) => session.id === sessionId);
  if (hit) return hit;
  const all = await context.sessions.listAll({ pageLimit: 1000 });
  return all.find((session) => session.id === sessionId) ?? null;
}

export interface ReviewPage {
  refresh(): Promise<void>;
  dispose(): void;
}

export async function mountReview(
  root: HTMLElement,
  context: ExtensionContext,
  now: () => number = Date.now,
): Promise<ReviewPage> {
  const sessionId = context.invocation.conversationId || null;
  const main = el("main", { class: "page", "aria-labelledby": "page-title" });
  const content = el("div", { class: "stack" });
  main.append(el("h1", { id: "page-title" }, "Review checklist"), content);
  root.replaceChildren(main);

  let saveState: SaveState = { kind: "idle" };
  const saveStatus = el("p", { class: "save-status", id: "save-status" });
  const store = new ChecklistStore(context.storage.user, (state) => {
    saveState = state;
    saveStatus.textContent = saveStateText(state);
    saveStatus.classList.toggle("is-error", state.kind === "error");
  });

  let data: ChecklistData = { templates: [], defaults: { projects: {} }, progress: {} };
  let session: Session | null = null;
  let projects: ExtensionProjectSummary[] = [];
  let pullRequest: PullRequestState = { kind: "loading" };
  let loadError: string | null = null;
  let loaded = false;

  const renderRecent = async (container: HTMLElement) => {
    container.replaceChildren(el("p", { class: "muted" }, "Loading recent sessions…"));
    try {
      const page = await context.sessions.listPage({ limit: 10 });
      const recent = [...page.sessions].sort((left, right) => right.updatedAt - left.updatedAt);
      if (recent.length === 0) {
        container.replaceChildren(el("p", { class: "muted" }, "No sessions yet."));
        return;
      }
      container.replaceChildren(
        el("h2", { id: "recent-title" }, "Recent sessions"),
        el(
          "ul",
          { class: "recent", "aria-labelledby": "recent-title" },
          ...recent.map((entry) => {
            const title = entry.title || "Untitled session";
            return el(
              "li",
              {},
              el(
                "span",
                { class: "recent-text" },
                el("span", { class: "recent-title" }, title),
                el("span", { class: "muted" }, ` · ${STATUS[entry.status].label} · updated ${relativeTime(entry.updatedAt * 1000, now())}`),
              ),
              button("Open session", () => void context.navigation.openSession(entry.id), {
                "aria-label": `Open session ${title}`,
              }),
            );
          }),
        ),
      );
    } catch (error) {
      container.replaceChildren(el("p", { class: "error" }, `Couldn't list sessions: ${errorMessage(error)}`));
    }
  };

  const sessionBlock = (current: Session): HTMLElement => {
    const status = STATUS[current.status];
    const project = current.projectId ? projects.find((entry) => entry.id === current.projectId) : undefined;
    const facts = el("dl", { class: "facts" });
    const fact = (term: string, value: Node | string) => facts.append(el("dt", {}, term), el("dd", {}, value));
    fact(
      "Status",
      el("span", { class: `chip status-${current.status}`, "data-testid": "status-chip" },
        el("span", { "aria-hidden": "true", class: "chip-icon" }, status.icon), status.label),
    );
    fact("Branch", current.gitBranch ? el("code", {}, current.gitBranch) : "No worktree branch");
    if (current.projectId) fact("Project", project?.name ?? "A project you can't see");
    fact("Updated", relativeTime(current.updatedAt * 1000, now()));
    fact("Session id", el("code", { id: "session-id" }, current.id));

    const prLine = el("p", { class: "pr", id: "pull-request" });
    if (pullRequest.kind === "loading") prLine.append("Checking for a pull request…");
    else if (pullRequest.kind === "error") {
      prLine.append(`Couldn't check for a pull request: ${pullRequest.message}`);
    }
    else if (!pullRequest.pr) prLine.append("No pull request found for this session's branch");
    else {
      const pr = pullRequest.pr;
      prLine.append(
        el("span", {}, `#${pr.number} · ${pr.title} · ${pr.state}`),
        " ",
        button("Open pull request", () => void context.navigation.openExternal(pr.url), {
          class: "link-button",
          "data-key": "open-pr",
        }),
      );
    }
    return el(
      "section",
      { class: "card", "aria-labelledby": "reviewing-title" },
      el("h2", { id: "reviewing-title" }, "Reviewing"),
      el(
        "p",
        { class: "session-title" },
        el("strong", { id: "session-title" }, current.title || "Untitled session"),
        current.titleProvisional ? el("span", { class: "muted" }, " (provisional title)") : null,
      ),
      facts,
      prLine,
      el(
        "div",
        { class: "actions" },
        button("Open session", () => void context.navigation.openSession(current.id), { "data-key": "open-session" }),
        button("Refresh", () => void refresh(), { "data-key": "refresh" }),
      ),
    );
  };

  const checklistBlock = (current: Session): HTMLElement => {
    const { template, source } = resolveTemplate({
      sessionId: current.id,
      projectId: current.projectId,
      templates: data.templates,
      defaults: data.defaults,
      progress: data.progress,
    });
    const total = itemsOf(template).length;
    const progressText = el("p", { id: "progress", class: "progress", "aria-live": "polite" });
    const updateProgress = () => {
      progressText.textContent = `${checkedCount(data.progress[current.id], template)} of ${total} checked`;
    };
    updateProgress();

    const select = el("select", { id: "template-select", "data-key": "template-select" });
    for (const option of allTemplates(data.templates)) {
      const node = el("option", { value: option.id }, option.name);
      node.selected = option.id === template.id;
      select.append(node);
    }
    select.addEventListener("change", () => {
      data.progress = chooseTemplate(data.progress, current.id, select.value, now());
      store.saveProgress(current.id, data.progress[current.id]);
      render();
    });

    const checked = new Set(data.progress[current.id]?.c ?? []);
    const groups = template.sections.map((section) => {
      const list = el(
        "ul",
        { class: "items" },
        ...section.items.map((item) => {
          const box = el("input", { type: "checkbox", id: `item-${item.id}`, "data-key": `item:${item.id}` });
          box.checked = checked.has(item.id);
          box.addEventListener("change", () => {
            data.progress = setChecked(data.progress, current.id, template, item.id, box.checked, now());
            store.saveProgress(current.id, data.progress[current.id]);
            updateProgress();
          });
          return el("li", {}, el("label", { class: "item", for: `item-${item.id}` }, box, el("span", {}, item.text)));
        }),
      );
      return section.heading
        ? el("fieldset", {}, el("legend", {}, section.heading), list)
        : el("div", { role: "group", "aria-label": template.name }, list);
    });

    const uncheck = button("Uncheck all", () =>
      confirmInline(uncheck, "Uncheck every item?", "Uncheck all", () => {
        data.progress = uncheckAll(data.progress, current.id, template, now());
        store.saveProgress(current.id, data.progress[current.id]);
        render();
      }), { "data-key": "uncheck-all" });

    return el(
      "section",
      { class: "card", "aria-labelledby": "checklist-title" },
      el("h2", { id: "checklist-title" }, "Checklist"),
      el(
        "div",
        { class: "picker" },
        el("label", { for: "template-select" }, "Template"),
        select,
        el("p", { class: "muted", id: "template-source" }, `From: ${SOURCE_LABELS[source]}`),
        source === "session"
          ? button("Use the default again", () => {
              data.progress = chooseTemplate(data.progress, current.id, undefined, now());
              store.saveProgress(current.id, data.progress[current.id]);
              render();
            }, { class: "link-button", "data-key": "use-default" })
          : null,
      ),
      templateChangedSinceTicks(data.progress[current.id], template)
        ? el("p", { class: "notice" }, "This template changed since you started.")
        : null,
      ...groups,
      progressText,
      el("div", { class: "actions" }, uncheck),
      el("p", { class: "storage-notice", id: "storage-notice" },
        el("span", { "aria-hidden": "true" }, "ⓘ "),
        store.available ? BROWSER_ONLY_NOTICE : UNAVAILABLE_NOTICE),
      saveStatus,
    );
  };

  const render = () => {
    renderKeepingFocus(content, () => {
      if (!sessionId) {
        const recent = el("div", { class: "card" });
        void renderRecent(recent);
        return [el("p", { class: "lead" }, "Open the review checklist from a session's header or composer."), recent];
      }
      if (!loaded) return [el("p", { class: "muted" }, "Loading session…")];
      if (loadError) {
        return [
          el("p", { class: "error", role: "alert" }, `Couldn't load this session: ${loadError}`),
          button("Try again", () => void refresh(), { "data-key": "refresh" }),
        ];
      }
      if (!session) {
        return [
          el("p", { class: "lead", id: "unavailable" },
            "This session isn't available here. It may be archived, a sub-agent session, or not shared with you."),
        ];
      }
      const banner = bannerFor(session);
      return [
        sessionBlock(session),
        banner
          ? el("p", { class: "banner", role: "status", id: "banner" }, el("span", { "aria-hidden": "true" }, "⚠ "), banner)
          : null,
        checklistBlock(session),
      ].filter((node): node is HTMLElement => node !== null);
    });
    saveStatus.textContent = saveStateText(saveState);
  };

  const loadPullRequest = async (current: Session) => {
    pullRequest = { kind: "loading" };
    try {
      pullRequest = { kind: "done", pr: await context.sessions.pullRequest(current.id) };
    } catch (error) {
      pullRequest = { kind: "error", message: errorMessage(error) };
    }
    if (session?.id === current.id) render();
  };

  const refresh = async () => {
    if (!sessionId) return render();
    try {
      const [found, projectList] = await Promise.all([
        findSession(context, sessionId),
        context.projects.list().catch(() => projects),
      ]);
      session = found;
      projects = projectList;
      loadError = null;
    } catch (error) {
      loadError = errorMessage(error);
    }
    loaded = true;
    render();
    if (session) void loadPullRequest(session);
  };

  data = await store.load();
  render();
  await refresh();

  const onVisible = () => {
    if (document.visibilityState === "visible") void refresh();
  };
  document.addEventListener("visibilitychange", onVisible);
  return {
    refresh,
    dispose() {
      document.removeEventListener("visibilitychange", onVisible);
      store.flush();
    },
  };
}
