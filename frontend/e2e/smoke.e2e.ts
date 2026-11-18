import { expect, test } from "@playwright/test";

// The account-free pages a first-time visitor sees. Without a backend, live
// research requests fail (503) and the pages must still render their content.
const pages = [
  { path: "/", heading: "On your radar" },
  { path: "/stocks/AAPL", heading: "Apple · AAPL" },
  { path: "/trending", heading: "What’s moving. What matters." },
  { path: "/industries", heading: "Every industry has a story." },
  { path: "/login", heading: "Welcome back." },
  { path: "/privacy", heading: "Privacy at Folio" },
  { path: "/terms", heading: null },
];

for (const { path, heading } of pages) {
  test(`${path} renders without a page error`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    const response = await page.goto(path, { waitUntil: "networkidle" });

    expect(response?.status()).toBe(200);
    if (heading) await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    else await expect(page.getByRole("heading").first()).toBeVisible();
    expect(errors).toEqual([]);
  });
}
