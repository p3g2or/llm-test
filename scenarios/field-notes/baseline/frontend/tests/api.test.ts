import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/api";
import { note } from "./fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("encodes filters and reads note JSON", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify([note])));
    vi.stubGlobal("fetch", fetch);
    expect(await api.list("work", " tea & coffee ")).toEqual([note]);
    expect(fetch).toHaveBeenCalledWith("/api/notes?category=work&q=tea+%26+coffee", undefined);
  });

  it("sends JSON when creating a note", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(note), { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    const draft = { title: note.title, body: note.body, category: note.category };
    expect(await api.create(draft)).toEqual(note);
    expect(fetch).toHaveBeenCalledWith("/api/notes", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
    });
  });

  it("handles an empty 204 response", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    await expect(api.remove(note.id)).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith(`/api/notes/${note.id}`, { method: "DELETE" });
  });

  it.each([
    [JSON.stringify({ detail: "Note not found" }), 404, "Note not found"],
    ["bad gateway", 502, "Request failed (502)"],
    [JSON.stringify({ detail: [{ msg: "invalid" }] }), 422, "Request failed (422)"],
  ])("reports server errors safely", async (body, status, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status })));
    await expect(api.list()).rejects.toThrow(message);
  });
});
