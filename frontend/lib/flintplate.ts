import { request } from "./api";
import { auth } from "./auth";

export interface Venue { id:string; name:string; role:"manager"|"service"|"kitchen"; timezone:string; currency:string; guest_enabled:boolean; guest_table_orders:boolean; guest_open_tables:boolean; tip_mode:string; tip_kitchen_bps:number; guestbook_retention_days?:number }
export interface Floor { id:string; name:string; level:number }
export interface Room { id:string; name:string; floor_id:string }
export interface Resource { id:string; name:string; area:string; room_id:string|null; kind:string; seats:number; x:number; y:number; version:number; hourly_rate_cents:number; billing_minutes:number; tax_rate_bps:number; tags:string[]; min_party:number; combinable_with:string[] }
export interface ProposalOption { key:string; title:string; summary:string; table_ids:string[]; table_names:string[]; seats:number; starts_at:string; ends_at:string; score:number; reasons:string[]; tradeoffs:string[] }
export interface Proposal { decision_id:string; engine:string; prompt_applied:boolean; prompt_note:string; considered:number; options:ProposalOption[]; notes:string[] }
export interface Criterion { id:string; label:string; text:string; active:boolean; kind:string; version:number }
export type Station = "service"|"kitchen"|"bar"|"activities";
export interface StationSnapshot { id:string; code:string; name:string; kind:Station }
export interface OperatingStation extends StationSnapshot { active:boolean; sort_order:number; version:number }
export interface ProfileTemplate { id:string; name:string; description:string; stations:Station[]; competence:number; active:boolean; version:number; members:number }
export interface StaffProfile { worker_id:string; full_name:string; role:string; active:boolean; template_id:string|null; template_name:string; stations:Station[]; competence:number; stations_source:"Vorlage"|"eigen"; competence_source:"Vorlage"|"eigen"; emergency_opt_in:boolean }
export interface ProfileChange { worker_id:string; full_name:string; field:"stations"|"competence"; before:unknown; after:unknown }
export interface ProfileImpact { changes:ProfileChange[]; shielded:{worker_id:string;full_name:string;fields:string[]}[]; affected_members:number }
export interface Packaging { name:string; price_cents:number; deposit_cents:number; tax_rate_bps:number; deposit_tax_rate_bps:number; reusable:boolean }
export interface MenuData { name:string; description:string; category:string; price_cents:number; tax_rate_bps:number; cost_cents:number; allergens:string[]; available:boolean; station:string; station_snapshot?:StationSnapshot|null; takeaway_packaging:Packaging|null; ingredients?:Ingredient[]; contains?:string[] }
export interface Item extends Omit<MenuData,"cost_cents"> { id:string; sku:string; version:number }
export interface Draft { id:string; sku:string; draft:MenuData; published:MenuData|null; version:number; published_version:number|null }
export interface Line { line_id:string; course:number; preparation_status:string; item_id:string; name:string; sku:string; kind:string; quantity:number; price_cents:number; total_cents:number; tax_cents:number; discount_cents:number; note:string; station:string; station_snapshot?:StationSnapshot|null }
export interface Order { cancelled_units?:{line_id:string;unit:number;gross_cents:number;tax_cents:number;execution_id:string}[]; fulfillment_status:string; payment_status:string; id:string; number:string; table_id:string|null; status:string; version:number; lines:Line[]; total_cents:number; subtotal_cents:number; discount_cents:number; discount_reason:string; voucher_cents:number; guests:number; note:string; created_at:string; fulfillment:string; pos_requested:boolean; tip_cents:number; tip_recipient_id?:string|null }
export interface TipShare { worker_id:string; full_name:string; pool:string; minutes:number; share_cents:number; reason:string }
export interface TipDistribution { payer_tips?:number; period_start:string; period_end:string; mode:string; kitchen_bps:number; total_cents:number; orders:number; shares:TipShare[]; notes:string[] }
export interface TipRun extends TipDistribution { id:string; note:string; created_at:string }
export interface GuestProfile { id:string; display_name:string; reference:string; birthday:string|null; account_id:string|null; consent_special:boolean; consent_at:string|null; version:number; created_at:string; notes:number; markers?:string[] }
export interface GuestNote { id:string; text:string; category:string; visibility:"team"|"private"; sensitive:boolean; author_id:string; author_name:string; mine:boolean; created_at:string; expires_at:string }
export interface GuestProfileDetail extends GuestProfile { entries:GuestNote[]; retention_days:number; markers:string[] }
export interface DietMarker { id:string; key:string; label:string; kind:"allergie"|"diaet"|"zustand"; special:boolean; legal_block:boolean; avoid:string[]; note:string; active:boolean; version:number }
export interface Ingredient { name:string; note:string; allergens:string[] }
export interface ItemDetail { id:string; sku:string; name:string; description:string; category:string; station:string; available:boolean; allergens:string[]; contains:string[]; ingredients:Ingredient[]; published:boolean }
export interface Verdict { item_id:string; name:string; state:"ok"|"warnung"|"gesperrt"; reasons:string[]; markers:string[] }
export interface CheckResult { markers:DietMarker[]; verdicts:Verdict[]; blocked:number; warned:number }
export interface Suggestion { item_id:string; name:string; price_cents:number; together:number; of_orders:number; share:number; reason:string }
export interface SuggestResult { basis:string; orders_seen:number; filtered_out:number; suggestions:Suggestion[] }
export interface ChatChannel { id:string; name:string; topic:string; unread:number; last_message_at:string|null }
export interface ChatMessage { id:string; text:string; author_id:string; author_name:string; mine:boolean; created_at:string; expires_at:string }
export interface Reservation { id:string; table_ids?:string[]; source?:string; note?:string; checked_in_at?:string|null; closed_at?:string|null; table_id:string; guest_name:string; guests:number; starts_at:string; ends_at:string; status:string; version:number }
export interface Usage { id:string; table_id:string; guest_name:string; starts_at:string; reserved_until:string; hourly_rate_cents:number; billing_minutes:number; order_id:string|null }
export interface Member { id:string; user_id:string; full_name:string; role:string; active:boolean }
export interface Shift { id:string; worker_id:string; starts_at:string; ends_at:string; station:string; station_label?:string|null; break_minutes:number; status:string; version:number }
export interface Overview { active_orders:number; open_total_cents:number; settled_total_cents:number; reserved_today:number; staff_today:number; available_items:number; hints:string[] }
export interface Device { id:string; name:string; kind:string; scopes:string[]; active:boolean; expires_at:string; last_seen_at:string|null }
export interface Voucher { id:string; label:string; initial_cents:number; balance_cents:number; expires_at:string; reference:string }
export interface Ticket { id:string; category:string; subject:string; description:string; status:string; created_at:string }
export interface TimeEntry { id:string; clock_in:string; clock_out:string|null; break_minutes:number; status:string; net_minutes:number|null }
export interface Link { id:string; org_id:string; content_id:string; type_key:string; expected_revision:number; version:number; status:string; last_error:string|null; last_synced_at:string|null }
export const money=(cents:number)=>new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR"}).format(cents/100);
export const time=(value:string,zone="Europe/Berlin")=>new Intl.DateTimeFormat("de-DE",{hour:"2-digit",minute:"2-digit",timeZone:zone}).format(new Date(value));
export const day=(value:string,zone="Europe/Berlin")=>new Intl.DateTimeFormat("de-DE",{day:"2-digit",month:"short",timeZone:zone}).format(new Date(value));
export const date=(value:string,zone="Europe/Berlin")=>new Intl.DateTimeFormat("de-DE",{day:"2-digit",month:"2-digit",year:"numeric",timeZone:zone}).format(new Date(value));
export const labels:Record<string,string>={refunded:"Erstattet",partially_refunded:"Teilweise erstattet",refund_pending:"Erstattung offen",adjusted:"Forderung korrigiert",paid:"Bezahlt",partial:"Teilbezahlt",unpaid:"Unbezahlt",sent:"Neu",preparing:"In Zubereitung",ready:"Abholbereit",served:"Serviert",settled:"Bezahlt",cancelled:"Storniert",confirmed:"Bestätigt",seated:"Eingecheckt",completed:"Abgeschlossen",draft:"Entwurf",submitted:"Zur Prüfung",approved:"Freigegeben",rejected:"Abgelehnt",correction_requested:"Korrektur angefragt",published:"Veröffentlicht",table:"Tisch",bowling:"Bowling",billiard:"Billard",pedal_boat:"Tretboot",activity:"Aktivität",service:"Service",manager:"Betriebsleitung",kitchen:"Küche"};
export function api<T>(path:string,method="GET",body?:unknown):Promise<T> {
  return request<T>(path,{method,...(body===undefined?{}:{body:JSON.stringify(body)}),cache:"no-store"},auth.getAccess()??undefined);
}
export function venueApi<T>(venue:string,path:string,method="GET",body?:unknown):Promise<T> { return api<T>(`/gastro/venues/${venue}${path}`,method,body); }
export const message=(error:unknown)=>error instanceof TypeError&&/fetch|network/i.test(error.message)?"Verbindung unterbrochen. Bitte erneut versuchen.":error instanceof Error?error.message:"Die Aktion konnte nicht abgeschlossen werden.";
export const toISO=(value:FormDataEntryValue|null)=>new Date(String(value)).toISOString();
export const num=(data:FormData,key:string)=>Number(data.get(key)??0);
export const str=(data:FormData,key:string)=>String(data.get(key)??"");
