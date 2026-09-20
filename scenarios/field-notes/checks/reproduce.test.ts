import { expect, it, vi } from "vitest";
import { mountApp } from "../src/app";
import { config, note } from "./fixtures";
import type { Note, Summary } from "../src/types";

it("preserves the benchmark's stale summary defect", async () => {
  const old = { total: 1, by_category: { work: 1, personal: 0, ideas: 0 } };
  const empty = { total: 0, by_category: { work: 0, personal: 0, ideas: 0 } };
  const api = {
    config: vi.fn().mockResolvedValue(config),
    list: vi.fn().mockResolvedValue([note]),
    summary: vi.fn().mockResolvedValue(old),
    create: vi.fn().mockResolvedValue(note),
    remove: vi.fn().mockResolvedValue(undefined),
  };
  const root = document.createElement("main");
  await mountApp(root, api);
  let list!: (value: Note[]) => void;
  let summary!: (value: Summary) => void;
  api.list.mockImplementationOnce(() => new Promise<Note[]>((resolve) => { list = resolve; }));
  api.summary.mockImplementationOnce(() => new Promise<Summary>((resolve) => { summary = resolve; }));
  root.querySelector(".filters")!.dispatchEvent(new Event("submit", { cancelable: true }));
  api.list.mockResolvedValueOnce([]);
  api.summary.mockResolvedValueOnce(empty);
  root.querySelector<HTMLButtonElement>("article button")!.click();
  await vi.waitFor(() => expect(root.querySelector(".summary")!.textContent).toBe("0 notes · 0 work · 0 personal · 0 ideas"));
  expect(root.querySelectorAll("article")).toHaveLength(0);
  list([note]); summary(old);
  await vi.waitFor(() => expect(root.querySelector(".summary")!.textContent).toBe("1 notes · 1 work · 0 personal · 0 ideas"));
  expect(root.querySelectorAll("article")).toHaveLength(0);
});
