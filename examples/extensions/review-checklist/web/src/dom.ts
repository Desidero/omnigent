// Small DOM helpers. Every string goes in as text, never as HTML.

type Child = Node | string | null | undefined | false;
type Attributes = Record<string, string | number | boolean | undefined>;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Attributes = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === false) continue;
    if (name === "class") element.className = String(value);
    else element.setAttribute(name, value === true ? "" : String(value));
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child);
  }
  return element;
}

export function button(
  label: string,
  onClick: (event: MouseEvent) => void,
  attributes: Attributes = {},
): HTMLButtonElement {
  const element = el("button", { type: "button", ...attributes }, label);
  element.addEventListener("click", onClick);
  return element;
}

/**
 * Swaps a button for an inline "are you sure" group. The sandbox has no
 * `allow-modals`, so `window.confirm` isn't available.
 */
export function confirmInline(
  trigger: HTMLButtonElement,
  question: string,
  confirmLabel: string,
  onConfirm: () => void,
): void {
  const group = el("span", { class: "confirm", role: "group", "aria-label": question });
  const restore = () => {
    group.replaceWith(trigger);
    trigger.focus();
  };
  const yes = button(confirmLabel, () => {
    group.replaceWith(trigger);
    onConfirm();
  }, { class: "danger" });
  group.append(el("span", {}, question), yes, button("Cancel", restore));
  group.addEventListener("keydown", (event) => {
    if (event.key === "Escape") restore();
  });
  trigger.replaceWith(group);
  yes.focus();
}

/** Re-renders *container* and puts focus back on the element with the same `data-key`. */
export function renderKeepingFocus(container: HTMLElement, render: () => Node[]): void {
  const active = document.activeElement as HTMLElement | null;
  const key = active && container.contains(active) ? active.dataset.key : undefined;
  container.replaceChildren(...render());
  if (!key) return;
  const target = [...container.querySelectorAll<HTMLElement>("[data-key]")].find(
    (element) => element.dataset.key === key,
  );
  target?.focus();
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}
