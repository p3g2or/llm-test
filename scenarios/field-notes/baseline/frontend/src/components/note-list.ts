import type { Note } from "../types";

export function noteList(notes: Note[], onDelete: (id: string) => Promise<void>): HTMLElement {
  const list = document.createElement("div");
  list.className = "note-list";
  if (!notes.length) {
    const empty = document.createElement("p");
    empty.textContent = "No notes match. Add a note or change your filters.";
    list.append(empty);
  }
  for (const note of notes) {
    const article = document.createElement("article");
    const title = document.createElement("h3");
    title.textContent = note.title;
    const meta = document.createElement("p");
    meta.className = "meta";
    const time = document.createElement("time");
    time.dateTime = note.created_at;
    time.textContent = new Date(note.created_at).toLocaleString();
    meta.append(`${note.category} · `, time);
    const body = document.createElement("p");
    body.className = "note-body";
    body.textContent = note.body;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = "Delete";
    button.setAttribute("aria-label", `Delete ${note.title}`);
    const error = document.createElement("p");
    error.className = "error";
    error.setAttribute("role", "alert");
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      button.disabled = true;
      error.textContent = "";
      try { await onDelete(note.id); }
      catch (reason) {
        error.textContent = reason instanceof Error ? reason.message : "Could not delete note.";
      } finally { button.disabled = false; }
    });
    article.append(title, meta, body, button, error);
    list.append(article);
  }
  return list;
}
