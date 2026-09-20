import type { Category, NewNote, PublicConfig } from "../types";

export function noteForm(config: PublicConfig, onCreate: (note: NewNote) => Promise<void>): HTMLFormElement {
  const form = document.createElement("form");
  form.className = "note-form";
  form.innerHTML = `
    <h2>New note</h2>
    <label>Title<input name="title" required /></label>
    <label>Category<select name="category"></select></label>
    <label>Note<textarea name="body" rows="5" required></textarea></label>
    <p class="error" role="alert"></p>
    <button type="submit">Add note</button>`;
  const title = form.querySelector<HTMLInputElement>("input")!;
  const body = form.querySelector<HTMLTextAreaElement>("textarea")!;
  const category = form.querySelector<HTMLSelectElement>("select")!;
  const button = form.querySelector<HTMLButtonElement>("button")!;
  const error = form.querySelector<HTMLElement>(".error")!;
  title.maxLength = config.title_limit;
  body.maxLength = config.body_limit;
  for (const value of config.categories) category.add(new Option(value, value));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return;
    error.textContent = "";
    if (!title.value.trim() || !body.value.trim()) {
      error.textContent = "Enter a title and a note.";
      return;
    }
    button.disabled = true;
    try {
      await onCreate({ title: title.value.trim(), body: body.value.trim(), category: category.value as Category });
      form.reset();
      title.focus();
    } catch (reason) {
      error.textContent = reason instanceof Error ? reason.message : "Could not save note.";
    } finally {
      button.disabled = false;
    }
  });
  return form;
}
