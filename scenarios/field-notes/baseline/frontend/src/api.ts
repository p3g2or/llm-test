import type { Category, NewNote, Note, PublicConfig, Summary } from "./types";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data: unknown = await response.json();
      if (typeof data === "object" && data !== null && "detail" in data &&
          typeof data.detail === "string") message = data.detail;
    } catch { /* The server may return a non-JSON error page. */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  config: () => request<PublicConfig>("/config"),
  summary: () => request<Summary>("/summary"),
  list: (category: Category | "" = "", q = "") => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (q.trim()) params.set("q", q.trim());
    return request<Note[]>(`/notes?${params}`);
  },
  create: (note: NewNote) => request<Note>("/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(note),
  }),
  remove: (id: string) => request<void>(`/notes/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

export type NotesApi = typeof api;
