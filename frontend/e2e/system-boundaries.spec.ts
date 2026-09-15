import { expect, test } from "@playwright/test";
import { randomInt } from "node:crypto";

async function registerAndOnboard(page: import("@playwright/test").Page) {
  const phone = `+2556${randomInt(0, 100_000_000).toString().padStart(8, "0")}`;
  await page.goto("/auth/register");
  await page.locator('input[autocomplete="tel"]').fill(phone);
  await page.locator('input[autocomplete="new-password"]').fill("playwright-password-123");
  await page.locator("form button:not([type=button])").click();
  await page.getByRole("button", { name: /Tuma namba|Send code/i }).click();
  const codeText = await page.getByText(/Dev code:/).textContent();
  const code = codeText?.match(/\d{6}/)?.[0];
  expect(code).toBeTruthy();
  await page.locator('input[placeholder="123456"]').fill(code!);
  await page.getByRole("button", { name: /Thibitisha|Verify/i }).click();
  await expect(page).toHaveURL(/\/onboarding/);
  await page.getByRole("button", { name: /Ruka|Skip/i }).click();
  await expect(page).toHaveURL(/\/app\/projects/);
}

test("public/private route gates are visible and deterministic", async ({ page }) => {
  await page.goto("/app/library");
  await expect(page).toHaveURL(/\/app\/library/);
  await page.goto("/app/projects");
  await expect(page).toHaveURL(/\/auth\/login/);
});

test("dataset upload, admin denial and logout boundaries", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one full boundary journey is sufficient");
  await registerAndOnboard(page);

  const result = await page.evaluate(async () => {
    const created = await fetch("/api/projects/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "E2E dataset", mode: "researcher" }),
    });
    const project = await created.json();
    const form = new FormData();
    form.set("file", new File(["region,value\nDodoma,4\nMwanza,7\n"], "sample.csv", {
      type: "text/csv",
    }));
    const uploaded = await fetch(`/api/datasets/${project.id}`, {
      method: "POST", headers: { "Idempotency-Key": "playwright-upload-1" }, body: form,
    });
    return { createStatus: created.status, uploadStatus: uploaded.status, body: await uploaded.json() };
  });
  expect(result.createStatus).toBe(201);
  expect(result.uploadStatus).toBe(201);
  expect(result.body.id).toBeTruthy();
  // CI intentionally runs without Redis: profiling completes inline there.
  // A deployed Redis path instead returns the durable job identifier.
  expect(Boolean(result.body.job_id) || result.body.status === "ready").toBeTruthy();

  await page.goto("/admin");
  await expect(page.getByText(/Admin access required/i)).toBeVisible();

  await page.evaluate(() => fetch("/api/session/logout", { method: "POST" }));
  await page.goto("/app/projects");
  await expect(page).toHaveURL(/\/auth\/login/);
});

test("messages remain isolated when one project has multiple chats", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one full multi-chat journey is sufficient");
  await registerAndOnboard(page);

  const result = await page.evaluate(async () => {
    const created = await fetch("/api/projects/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "E2E multi-chat", mode: "researcher" }),
    });
    const project = await created.json();
    const firstList = await fetch(`/api/projects/${project.id}/threads`);
    const first = (await firstList.json())[0];
    const secondResponse = await fetch(`/api/projects/${project.id}/threads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Second chat" }),
    });
    const second = await secondResponse.json();

    async function send(threadId: string, marker: string) {
      const response = await fetch(`/api/chat/${project.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: marker,
          language: "en",
          effort: "spool",
          thread_id: threadId,
          services: {},
        }),
      });
      await response.text();
      return response.status;
    }

    const firstStatus = await send(first.id, "FIRST-CHAT-MARKER");
    const secondStatus = await send(second.id, "SECOND-CHAT-MARKER");
    const firstMessages = await (
      await fetch(`/api/projects/${project.id}/threads/${first.id}/messages`)
    ).json();
    const secondMessages = await (
      await fetch(`/api/projects/${project.id}/threads/${second.id}/messages`)
    ).json();
    await fetch(`/api/projects/${project.id}`, { method: "DELETE" });
    return { firstStatus, secondStatus, firstMessages, secondMessages };
  });

  expect(result.firstStatus).toBe(200);
  expect(result.secondStatus).toBe(200);
  expect(result.firstMessages.some((m: { content_en: string }) =>
    m.content_en === "FIRST-CHAT-MARKER")).toBeTruthy();
  expect(result.firstMessages.some((m: { content_en: string }) =>
    m.content_en === "SECOND-CHAT-MARKER")).toBeFalsy();
  expect(result.secondMessages.some((m: { content_en: string }) =>
    m.content_en === "SECOND-CHAT-MARKER")).toBeTruthy();
  expect(result.secondMessages.some((m: { content_en: string }) =>
    m.content_en === "FIRST-CHAT-MARKER")).toBeFalsy();
});

test("a repaired artifact updates its verification state in place", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one artifact-state journey is sufficient");
  const hydrationErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /hydration failed/i.test(message.text())) {
      hydrationErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    if (/hydration failed/i.test(error.message)) hydrationErrors.push(error.message);
  });
  await registerAndOnboard(page);
  const project = await page.evaluate(async () => {
    const response = await fetch("/api/projects/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "E2E artifact repair", mode: "researcher" }),
    });
    return response.json();
  });
  const artifactUrl = "/api/artifact/e2e/repaired.json?exp=4102444800&sig=e2e";
  await page.route(`**/api/chat/${project.id}`, async (route) => {
    const frames = [
      ["turn", { turn_id: "e2e-repair-turn", resumable: true }],
      ["artifact", {
        seq: 0, url: artifactUrl, name: "repaired.json", mime: "application/json",
        verified: false, defects: ["initial render failed"],
      }],
      ["artifact", {
        seq: 1, url: artifactUrl, name: "repaired.json", mime: "application/json",
        verified: true, defects: [],
      }],
      ["token", { seq: 2, text: "The repaired artifact is ready." }],
      ["done", { seq: 3, message_id: "e2e-repair-turn" }],
    ];
    const body = frames
      .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
      .join("");
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream; charset=utf-8",
      headers: { "Cache-Control": "no-cache, no-transform" },
      body,
    });
  });

  await page.goto(`/app/chat/${project.id}`);
  await page.locator("textarea").fill("Repair this artifact");
  await page.locator("textarea").press("Enter");
  await expect(page.locator("figure.inline-artifact")).toHaveCount(1);
  await expect(page.getByText(/Verified|Imehakikiwa/)).toBeVisible();
  await expect(page.getByText(/Has known faults|Ina hitilafu/)).toHaveCount(0);
  expect(hydrationErrors).toEqual([]);
  await page.evaluate((id) => fetch(`/api/projects/${id}`, { method: "DELETE" }), project.id);
});
