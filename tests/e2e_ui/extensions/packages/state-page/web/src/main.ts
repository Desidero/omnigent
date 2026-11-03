import { defineExtension, ExtensionApiError } from "@omnigent/extension-sdk";

const ID = "omnigent-test.state-page";

defineExtension({
  activate(context) {
    const root = document.getElementById("root");
    if (!root) throw new Error("Extension root is missing");
    root.innerHTML = `
      <button id="watch" type="button">Watch PR 7</button>
      <button id="summarize" type="button">Summarize</button>
      <output id="result"></output>`;
    const result = root.querySelector<HTMLOutputElement>("#result")!;
    const run = (action: () => Promise<unknown>) => async () => {
      try {
        result.textContent = JSON.stringify(await action());
      } catch (error) {
        result.textContent = `error:${error instanceof ExtensionApiError ? error.code : "unknown"}`;
      }
    };
    root.querySelector("#watch")!.addEventListener(
      "click",
      run(async () => {
        await context.commands.invoke(`${ID}.watch`, { pr: "7" });
        const entry = await context.state.get("pr:7");
        const page = await context.state.list();
        return { value: entry?.value, keys: page.entries.map((item) => item.key) };
      }),
    );
    root.querySelector("#summarize")!.addEventListener(
      "click",
      run(async () => {
        const outcome = await context.commands.invoke(`${ID}.summarize`, {
          text: "Watching 2 PRs",
        });
        return outcome.publishedFields;
      }),
    );
  },
});
