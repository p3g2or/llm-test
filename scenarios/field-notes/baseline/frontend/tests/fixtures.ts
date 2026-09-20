import type { Note, PublicConfig } from "../src/types";

export const config: PublicConfig = {
  board_title: "Team Notes", title_limit: 100, body_limit: 4000,
  categories: ["work", "personal", "ideas"],
};
export const note: Note = {
  id: "00000000-0000-0000-0000-000000000001", title: "Release checklist",
  body: "Review deployment", category: "work", created_at: "2026-01-01T12:00:00Z",
};
