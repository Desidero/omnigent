import {
  defineExtension,
  type Disposable,
  type ExtensionContext,
  ExtensionApiError,
} from "@omnigent/extension-sdk";
import { type GoalsView, isWatched, parseView, rowView } from "./model";
import "./style.css";

const ID = "desidero.goal-loop";
const POLL_MS = 5000;

let theme: Disposable | null = null;
let timer: ReturnType<typeof setInterval> | null = null;

type Child = Node | string | null | false;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Record<string, string | boolean | undefined> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === false) continue;
    if (name === "class") element.className = value as string;
    else element.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children) if (child) element.append(child);
  return element;
}

function message(error: unknown): string {
  if (error instanceof ExtensionApiError && error.code === "PermissionDenied") {
    return "You need edit access to this session to change its goals.";
  }
  return error instanceof Error ? error.message : "Something went wrong";
}

function mount(root: HTMLElement, context: ExtensionContext): void {
  let view: GoalsView = parseView(null);
  let confirming = false;
  // Learned from the first command: viewers without edit access only read.
  let readOnly = false;
  const status = el("p", { class: "status", role: "status" });
  const body = el("div", { class: "stack" });
  root.replaceChildren(
    el(
      "main",
      { class: "page" },
      el("h1", {}, "Goals"),
      el(
        "p",
        { class: "muted" },
        "Keep this session's pull requests green: when a check fails, a maintainer " +
          "reviews or a conflict appears, the agent is woken at its next idle moment.",
      ),
      body,
      status,
    ),
  );

  async function load(): Promise<void> {
    const entry = await context.state.get("goals");
    view = parseView(entry?.value);
    render();
  }

  async function run(commandId: string, args: Record<string, string> = {}): Promise<void> {
    status.textContent = "";
    try {
      await context.commands.invoke(`${ID}.${commandId}`, args);
      await load();
    } catch (error) {
      status.textContent = message(error);
    }
  }

  function render(): void {
    const all = el("input", {
      type: "checkbox",
      id: "all",
      checked: view.all,
      disabled: readOnly,
    });
    all.addEventListener("change", () => void run("all", { mode: all.checked ? "on" : "off" }));
    const rows = view.items.map((item) => {
      const box = el("input", {
        type: "checkbox",
        id: `pr-${item.id}`,
        checked: isWatched(view, item),
        disabled: readOnly,
        "aria-describedby": `pr-${item.id}-status`,
      });
      box.addEventListener(
        "change",
        () => void run("pr", { pr: item.id, mode: box.checked ? "on" : "off" }),
      );
      const row = rowView(item, readOnly);
      return el(
        "li",
        { class: `goal goal-${item.status || "none"}` },
        box,
        el(
          "label",
          { for: `pr-${item.id}` },
          el("strong", {}, item.label),
          " ",
          item.title || item.url,
        ),
        el("span", { class: "detail", id: `pr-${item.id}-status` }, row.detail),
        row.resume
          ? button(`Resume ${item.label}`, "resume", () => void run("resume", { pr: item.id }))
          : null,
      );
    });
    const stop = el("button", { type: "button", class: "danger" }, "Stop all goals");
    stop.addEventListener("click", () => {
      confirming = true;
      render();
    });
    const confirm = el(
      "span",
      { class: "confirm", role: "group", "aria-label": "Stop every goal?" },
      "Stop every goal in this session? ",
      button("Stop all", "danger", () => {
        confirming = false;
        void run("stop");
      }),
      button("Cancel", "", () => {
        confirming = false;
        render();
      }),
    );
    const children: Child[] = [
      el("label", { class: "all" }, all, " All PRs in this session"),
      rows.length
        ? el("ul", { class: "goals" }, ...rows)
        : el("p", { class: "muted" }, "This session has no linked pull requests yet."),
      !view.enabled && (view.all || view.items.some((item) => item.toggle === "on"))
        ? el(
            "p",
            { class: "warning" },
            "Nobody is recorded as turning these goals on, so the agent won't be woken. " +
              "Turn a goal off and on again.",
          )
        : null,
      readOnly
        ? el("p", { class: "muted" }, "People who can edit this session can change its goals.")
        : confirming
          ? confirm
          : stop,
    ];
    body.replaceChildren(...children.filter((child): child is Node | string => Boolean(child)));
  }

  function button(label: string, tone: string, onClick: () => void): HTMLButtonElement {
    const element = el("button", { type: "button", class: tone || undefined }, label);
    element.addEventListener("click", onClick);
    return element;
  }

  async function start(): Promise<void> {
    await load().catch(() => undefined);
    // Ask for a fresh view (it lists the session's PRs). Only editors may; for
    // anyone else this is how the page learns it is read-only, so it stays quiet.
    try {
      await context.commands.invoke(`${ID}.refresh`);
      await load();
    } catch (error) {
      if (error instanceof ExtensionApiError && error.code === "PermissionDenied") {
        readOnly = true;
        render();
      }
    }
  }

  render();
  void start();
  timer = setInterval(() => void load().catch(() => undefined), POLL_MS);
}

defineExtension({
  async activate(context) {
    const root = document.getElementById("root");
    if (!root) throw new Error("Extension root is missing");
    const current = await context.theme.getCurrent();
    document.documentElement.dataset.theme = current.theme;
    theme = await context.theme.subscribe((next) => {
      document.documentElement.dataset.theme = next.theme;
    });
    mount(root, context);
  },
  deactivate() {
    if (timer) clearInterval(timer);
    timer = null;
    theme?.dispose();
    theme = null;
  },
});
