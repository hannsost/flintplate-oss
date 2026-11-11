export interface LabourPeriod { valid_from: string; valid_until: string | null; hourly_cents: number; employer_markup_bps: number; source_reference: string }
export interface LabourRevision { id: string; worker_id: string; previous_id: string | null; version: number; currency: string; actor_id: string; created_at: string; reason: string; source_reference: string; periods: LabourPeriod[] }
export interface LabourCurrent { worker_id: string; full_name: string; current: LabourRevision | null }
export const LABOUR_PENDING_PREFIX = "flintplate:labour-pending:v1:";
export const LABOUR_PATH = /^\/labour-rates\/[a-f0-9-]+$/;
const timeFormats = new Map<string, Intl.DateTimeFormat>();
const timeChoices = new Map<string, { iso: string; label: string }[]>();
export function labourLocalTime(iso: string, timezone: string): string {
  let format = timeFormats.get(timezone);
  if (!format) { format = new Intl.DateTimeFormat("sv-SE", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }); timeFormats.set(timezone, format); }
  const parts = format.formatToParts(new Date(iso));
  const value = (name: string) => parts.find(part => part.type === name)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")}T${value("hour")}:${value("minute")}`;
}
/** Empty means a nonexistent local wall time; two choices require an explicit
 * offset at the autumn clock change. Never silently pick either occurrence. */
export function labourTimeChoices(local: string, timezone: string) {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(local)) return [];
  const key = `${timezone}:${local}`, cached = timeChoices.get(key);
  if (cached) return cached;
  const guess = Date.parse(`${local}:00Z`);
  if (!Number.isFinite(guess)) return [];
  const choices: { iso: string; label: string }[] = [];
  for (let offset = -840; offset <= 840; offset += 15) {
    const iso = new Date(guess - offset * 60000).toISOString();
    if (labourLocalTime(iso, timezone) === local) choices.push({ iso, label: `UTC${offset < 0 ? "−" : "+"}${String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0")}:${String(Math.abs(offset) % 60).padStart(2, "0")}` });
  }
  if (timeChoices.size >= 512) timeChoices.clear();
  timeChoices.set(key, choices);
  return choices;
}
export function resolveLabourTime(local: string, timezone: string, selected: string, original?: string) {
  const choices = labourTimeChoices(local, timezone);
  if (!choices.length) throw new Error(`Die Ortszeit ${local.replace("T", " ")} existiert in ${timezone} nicht. Bitte einen gültigen Zeitpunkt wählen.`);
  const result = choices.length === 1 ? choices[0] : choices.find(choice => choice.iso === selected);
  if (!result) throw new Error("Diese Uhrzeit tritt bei der Zeitumstellung zweimal auf. Bitte den UTC-Versatz ausdrücklich wählen.");
  // Untouched API periods may contain seconds/microseconds beyond the minute
  // editor. Preserve them verbatim, including the chosen DST occurrence.
  if (original && labourLocalTime(original, timezone) === local && Math.floor(Date.parse(original) / 60000) === Math.floor(Date.parse(result.iso) / 60000)) return original;
  return result.iso;
}
