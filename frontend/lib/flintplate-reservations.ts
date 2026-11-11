import { inventoryApi } from "./flintplate-inventory";

export interface StockReservation {
  id: string; created_at: string; lot_id: string; location_id: string; quantity: string;
  expires_at: string; actor_id: string; reason: string;
  status: "active" | "undercovered" | "expired" | "released" | "consumed";
  covered_quantity: string; shortfall_quantity: string; blocked: boolean; lot_expired: boolean;
  consumable: boolean; closure_id: string | null; stock_operation_id: string | null;
  closed_at: string | null; closed_by: string | null; closure_reason: string;
}
export const reservationStatus: Record<StockReservation["status"], string> = {
  active: "Reserviert", undercovered: "Unterdeckt", expired: "Abgelaufen", released: "Freigegeben", consumed: "Verbraucht",
};
export function reservationApi<T>(venue: string, path = "", method = "GET", body?: unknown) {
  return inventoryApi<T>(venue, `/reservations${path}`, method, body);
}
