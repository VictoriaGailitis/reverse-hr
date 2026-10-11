import { test, expect } from "@playwright/test";
import { oauth, login, json } from "./helpers/backend";
const gradeNames = ["junior", "middle", "senior", "lead"];
const rows = gradeNames.map((grade) => ({
  grade,
  count: 10,
  mean_score: 65,
  sufficient: true,
  bands: { normal_from: 50, good_from: 80 },
  buckets: [
    { quality: "poor", count: 2, percent: 20 },
    { quality: "normal", count: 3, percent: 30 },
    { quality: "good", count: 5, percent: 50 },
  ],
}));
test("полосы качества: реальные пропорции, количество, hover и клавиатура", async ({
  page,
}) => {
  await oauth(page, false, ["content_admin"]);
  await page.route("**/api/assessment/v1/task-analytics/simulate", (route) => {
    const body = route.request().postDataJSON();
    expect(body.label_source).toBe("synthetic");
    expect(body.scale.by_grade.junior.normal_from).toBe(50);
    return json(route, {
      source: "synthetic",
      sample_count: 40,
      independent_label_count: 40,
      target_distributions: rows,
      independent_distributions: rows,
      contrasts: [
        {
          lower_grade: "junior",
          upper_grade: "middle",
          lower_count: 10,
          upper_count: 10,
          good_difference: 0.5,
          normal_or_better_difference: 0.3,
          status: "available",
        },
      ],
      corrected_item_total_correlation: 0.75,
      correlation_count: 40,
      correlation_status: "available",
      scale: body.scale,
      excluded: {},
      warnings: [],
    });
  });
  await login(page, "/admin?tab=analytics");
  await page.getByLabel(/Источник/).selectOption("synthetic");
  await page.getByRole("button", { name: "Рассчитать статистику" }).click();
  const bars = page.getByLabel("Распределение junior", { exact: true });
  await expect(bars).toHaveCount(2);
  const good = bars
    .first()
    .getByRole("button", { name: "Решена хорошо: 5 из 10 (50%)", exact: true });
  await expect(good).toHaveAttribute("style", /width: 50%/);
  await good.hover();
  await expect(good.getByRole("tooltip")).toBeVisible();
  await good.focus();
  await page.mouse.move(0, 0);
  await expect(good.getByRole("tooltip")).toBeVisible();
  await expect(page.getByText(/хорошо 50.0 п.п./)).toBeVisible();
  await page.screenshot({ path: "/tmp/reverse-hr-task-analytics.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await good.focus();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
