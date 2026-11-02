import { defineExtension, type Disposable } from "@omnigent/extension-sdk";
import { el } from "./dom";
import { mountReview } from "./review";
import { mountTemplates } from "./templates";
import "./style.css";

let themeSubscription: Disposable | null = null;
let page: { dispose(): void } | null = null;

defineExtension({
  async activate(context) {
    const root = document.getElementById("root");
    if (!root) throw new Error("Extension root is missing");
    const theme = await context.theme.getCurrent();
    document.documentElement.dataset.theme = theme.theme;
    themeSubscription = await context.theme.subscribe((next) => {
      document.documentElement.dataset.theme = next.theme;
    });
    if (context.view === "review") page = await mountReview(root, context);
    else if (context.view === "templates") page = await mountTemplates(root, context);
    else root.replaceChildren(el("p", {}, "Unknown page."));
  },
  deactivate() {
    page?.dispose();
    page = null;
    themeSubscription?.dispose();
    themeSubscription = null;
  },
});
