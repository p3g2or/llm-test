import { afterEach, expect, it, vi } from "vitest";
import { mountApp } from "../src/app";
import type { NotesApi } from "../src/api";
import type { Note } from "../src/types";
import { config, note } from "./fixtures";

function client() {
  return {
    config: vi.fn().mockResolvedValue(config),
    list: vi.fn().mockResolvedValue([note]),
    summary: vi.fn().mockResolvedValue({ total: 1, by_category: { work: 1, personal: 0, ideas: 0 } }),
    create: vi.fn().mockResolvedValue(note),
    remove: vi.fn().mockResolvedValue(undefined),
  } satisfies NotesApi;
}

function root(): HTMLElement {
  const element = document.createElement("main");
  document.body.append(element);
  return element;
}

afterEach(() => document.body.replaceChildren());

it("loads runtime configuration and filters notes", async () => {
  const api = client();
  const element = root();
  await mountApp(element, api);
  expect(element.querySelector("h1")!.textContent).toBe("Team Notes");
  expect(element.querySelector(".summary")!.textContent).toContain("1 work");
  const filters = element.querySelector<HTMLFormElement>(".filters")!;
  filters.querySelector("input")!.value = "checklist";
  filters.querySelector("select")!.value = "work";
  filters.dispatchEvent(new Event("submit", { cancelable: true }));
  await vi.waitFor(() => expect(api.list).toHaveBeenLastCalledWith("work", "checklist"));
});

it("refreshes after creation and deletion", async () => {
  const api = client();
  const element = root();
  await mountApp(element, api);
  const form = element.querySelector<HTMLFormElement>(".note-form")!;
  form.querySelector("input")!.value = "New";
  form.querySelector("textarea")!.value = "Body";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await vi.waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  element.querySelector<HTMLButtonElement>("article button")!.click();
  await vi.waitFor(() => expect(api.list).toHaveBeenCalledTimes(3));
  expect(api.remove).toHaveBeenCalledWith(note.id);
});

it("ignores outdated filter responses", async () => {
  const api = client();
  const element = root();
  await mountApp(element, api);
  let resolveOld!: (notes: Note[]) => void;
  api.list.mockImplementationOnce(() => new Promise<Note[]>((resolve) => { resolveOld = resolve; }));
  const form = element.querySelector(".filters")!;
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  api.list.mockResolvedValueOnce([{ ...note, title: "Current result" }]);
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await vi.waitFor(() => expect(element.textContent).toContain("Current result"));
  resolveOld([{ ...note, title: "Outdated result" }]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(element.textContent).not.toContain("Outdated result");
});

it("keeps a successful save separate from a failed refresh", async () => {
  const api = client();
  const element = root();
  await mountApp(element, api);
  api.list.mockRejectedValueOnce(new Error("Offline"));
  const form = element.querySelector<HTMLFormElement>(".note-form")!;
  form.querySelector("input")!.value = "Saved";
  form.querySelector("textarea")!.value = "Body";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await vi.waitFor(() => expect(form.querySelector("input")!.value).toBe(""));
  expect(element.querySelector(".load-error")!.textContent).toContain("Offline");
  expect(api.create).toHaveBeenCalledTimes(1);
});

it("provides a retry when configuration cannot load", async () => {
  const api = client();
  api.config.mockRejectedValueOnce(new Error("Offline"));
  const element = root();
  await mountApp(element, api);
  expect(element.textContent).toContain("Offline");
  element.querySelector("button")!.click();
  await vi.waitFor(() => expect(element.querySelector("h1")!.textContent).toBe("Team Notes"));
});
