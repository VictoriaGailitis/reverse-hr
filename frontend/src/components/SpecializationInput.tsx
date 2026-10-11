import { useId, type InputHTMLAttributes } from "react";

export const specializations = [
  ["backend", "Backend"],
  ["frontend", "Frontend"],
  ["mobile", "Mobile"],
  ["qa", "QA"],
  ["devops", "DevOps / SRE"],
  ["data_analytics", "Аналитика данных"],
  ["data_science", "Data Science / ML"],
  ["ux_ui", "UX/UI-дизайн"],
  ["project_manager", "Project Manager — управление проектами"],
  ["product_manager", "Product Manager — управление продуктом"],
  ["technical_manager", "Technical Manager — техническое управление"],
] as const;

export function managerAssessmentHint(value: string): string | undefined {
  switch (value) {
    case "project_manager":
      return "Видеоинтервью и доска: планирование, сроки, риски, зависимости и работа с командой.";
    case "product_manager":
      return "Видеоинтервью и доска: пользовательские проблемы, гипотезы, метрики и приоритизация.";
    case "technical_manager":
      return "Видеоинтервью и доска: технические решения, надёжность и организация разработки. Дополнительно — небольшие задания на код.";
    default:
      return undefined;
  }
}

export function SpecializationInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, "list">) {
  const id = useId();
  return (
    <>
      <input maxLength={100} {...props} list={id} />
      <datalist id={id}>
        {specializations.map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </datalist>
    </>
  );
}
