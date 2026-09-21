const { test, expect } = require("@playwright/test");

test("loads through the Home Assistant style proxy and persists a created note", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));

  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page.locator(".tree-wrapper")).toBeVisible({ timeout: 30_000 });

  const title = `CI note ${Date.now()}`;
  const body = "Created by the automated Home Assistant add-on browser test.";

  const created = await page.evaluate(async ({ title, body }) => {
    const csrfToken = globalThis.glob?.csrfToken;
    if (!csrfToken) {
      return { ok: false, status: 0, error: "missing csrf token" };
    }

    const response = await fetch("/api/notes/root/children?target=into", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-csrf-token": csrfToken
      },
      body: JSON.stringify({
        title,
        type: "text",
        mime: "text/html",
        content: `<p>${body}</p>`
      })
    });

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      // Some Trilium versions can return an empty body for mutations.
    }

    return { ok: response.ok, status: response.status, payload };
  }, { title, body });

  expect(created.ok, JSON.stringify(created)).toBe(true);

  await page.reload({ waitUntil: "networkidle" });
  const treeEntry = page.locator(".tree-wrapper").getByText(title, { exact: true }).first();
  await expect(treeEntry).toBeVisible({ timeout: 30_000 });
  await treeEntry.click();

  const titleField = page.locator(".note-split:not(.hidden-ext) .note-title").first();
  await expect(titleField).toBeVisible();
  const displayedTitle = await titleField.evaluate(element => element.value ?? element.textContent ?? "");
  expect(displayedTitle.trim()).toBe(title);

  await expect(page.locator(".note-split:not(.hidden-ext)")).toContainText(body, { timeout: 30_000 });
  expect(pageErrors).toEqual([]);
});
