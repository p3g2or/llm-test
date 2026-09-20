import { afterEach, expect, it, vi } from "vitest";
import { noteForm } from "../src/components/note-form";
import { noteList } from "../src/components/note-list";
import { config, note } from "./fixtures";

afterEach(() => document.body.replaceChildren());

it("uses configured limits, trims input, and resets after saving", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const form = noteForm(config, save);
  document.body.append(form);
  const title = form.querySelector("input")!;
  const body = form.querySelector("textarea")!;
  expect(title.maxLength).toBe(100);
  expect(body.maxLength).toBe(4000);
  title.value = " Meeting "; body.value = " Bring notes ";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  expect(form.querySelector("button")!.disabled).toBe(true);
  await vi.waitFor(() => expect(title.value).toBe(""));
  expect(save).toHaveBeenCalledWith({ title: "Meeting", body: "Bring notes", category: "work" });
  expect(form.querySelector("button")!.disabled).toBe(false);
});

it("rejects whitespace and preserves a failed submission", async () => {
  const save = vi.fn().mockRejectedValue(new Error("Storage offline"));
  const form = noteForm(config, save);
  form.querySelector("input")!.value = "   ";
  form.querySelector("textarea")!.value = "Body";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  expect(save).not.toHaveBeenCalled();
  expect(form.textContent).toContain("Enter a title and a note.");
  form.querySelector("input")!.value = "Keep me";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await vi.waitFor(() => expect(form.textContent).toContain("Storage offline"));
  expect(form.querySelector("input")!.value).toBe("Keep me");
  expect(form.querySelector("button")!.disabled).toBe(false);
});

it("renders user content as text and exposes delete errors", async () => {
  const remove = vi.fn().mockRejectedValue(new Error("Cannot delete"));
  const list = noteList([{ ...note, title: "<img src=x onerror=alert(1)>", body: "<script>bad</script>" }], remove);
  expect(list.querySelector("img,script")).toBeNull();
  expect(list.textContent).toContain("<script>bad</script>");
  list.querySelector("button")!.click();
  await vi.waitFor(() => expect(list.textContent).toContain("Cannot delete"));
  expect(remove).toHaveBeenCalledWith(note.id);
  expect(list.querySelector("button")!.disabled).toBe(false);
});

it("explains an empty list", () => {
  expect(noteList([], vi.fn()).textContent).toContain("No notes match");
});
