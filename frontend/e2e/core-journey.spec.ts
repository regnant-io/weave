import { expect, test } from "@playwright/test";
import { randomInt } from "node:crypto";

test("registration, phone verification and mobile-safe onboarding", async ({ page }) => {
  const phone = `+2557${randomInt(0, 100_000_000).toString().padStart(8, "0")}`;
  await page.goto("/auth/register");
  await page.locator('input[autocomplete="tel"]').fill(phone);
  await page.locator('input[autocomplete="new-password"]').fill("playwright-password-123");
  await page.locator("form button:not([type=button])").click();
  await expect(page).toHaveURL(/\/auth\/verify-otp/);

  await page.getByRole("button", { name: /Tuma namba|Send code/i }).click();
  const codeText = await page.getByText(/Dev code:/).textContent();
  const code = codeText?.match(/\d{6}/)?.[0];
  expect(code).toBeTruthy();
  await page.locator('input[placeholder="123456"]').fill(code!);
  await page.getByRole("button", { name: /Thibitisha|Verify/i }).click();
  await expect(page).toHaveURL(/\/onboarding/);

  // The route gate used to race the cookie write and loop back to onboarding.
  await page.getByRole("button", { name: /Ruka|Skip/i }).click();
  await expect(page).toHaveURL(/\/app\/projects/);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
