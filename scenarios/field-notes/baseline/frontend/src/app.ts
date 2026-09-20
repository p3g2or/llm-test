import { api, type NotesApi } from "./api";
import { noteForm } from "./components/note-form";
import { noteList } from "./components/note-list";
import type { Category } from "./types";

export async function mountApp(root: HTMLElement, client: NotesApi = api): Promise<void> {
  root.innerHTML = '<p role="status">Loading notes…</p>';
  try {
    const config = await client.config();
    root.innerHTML = `
      <header><h1></h1><p class="summary" role="status"></p></header>
      <div class="layout"><aside></aside><section aria-label="Notes">
        <form class="filters">
          <label>Search<input name="q" type="search" maxlength="100" /></label>
          <label>Category<select name="category"><option value="">All categories</option></select></label>
          <button type="submit">Filter</button>
        </form>
        <p class="load-error error" role="alert"></p>
        <div class="results" aria-live="polite"></div>
      </section></div>`;
    root.querySelector("h1")!.textContent = config.board_title;
    document.title = config.board_title;
    const filters = root.querySelector<HTMLFormElement>(".filters")!;
    const category = filters.querySelector<HTMLSelectElement>("select")!;
    const search = filters.querySelector<HTMLInputElement>("input")!;
    const results = root.querySelector<HTMLElement>(".results")!;
    const error = root.querySelector<HTMLElement>(".load-error")!;
    const summary = root.querySelector<HTMLElement>(".summary")!;
    for (const value of config.categories) category.add(new Option(value, value));
    let revision = 0;
    async function refresh(): Promise<void> {
      const current = ++revision;
      results.setAttribute("aria-busy", "true");
      error.textContent = "";
      try {
        const [notes, totals] = await Promise.all([
          client.list(category.value as Category | "", search.value), client.summary(),
        ]);
        summary.textContent = `${totals.total} notes · ` + config.categories
          .map((value) => `${totals.by_category[value]} ${value}`).join(" · ");
        if (current !== revision) return;
        results.replaceChildren(noteList(notes, async (id) => {
          await client.remove(id);
          await refresh();
        }));
      } catch (reason) {
        if (current !== revision) return;
        error.textContent = `${reason instanceof Error ? reason.message : "Could not load notes."} Use Filter to retry.`;
      } finally {
        if (current === revision) results.setAttribute("aria-busy", "false");
      }
    }
    root.querySelector("aside")!.append(noteForm(config, async (note) => {
      await client.create(note);
      // Refresh errors are shown separately so a successful save is never retried as a duplicate.
      await refresh();
    }));
    filters.addEventListener("submit", (event) => { event.preventDefault(); void refresh(); });
    await refresh();
  } catch (reason) {
    const message = document.createElement("p");
    message.setAttribute("role", "alert");
    message.textContent = reason instanceof Error ? reason.message : "Could not load the application.";
    const retry = document.createElement("button");
    retry.textContent = "Retry";
    retry.addEventListener("click", () => { void mountApp(root, client); });
    root.replaceChildren(message, retry);
  }
}
