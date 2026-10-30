import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";

dayjs.extend(utc);

/** 统一按 UTC 渲染（与服务端容器默认时区一致，避免随浏览器时区漂移）。 */
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.utc().format("YYYY-MM-DD HH:mm") : String(value);
}
