export interface DeliveryConfirmation {
  id: string; line_id: string; previous_id: string | null; version: number; status: "confirmed" | "cancelled"; expected_on: string;
  paid_quantity: string; bonus_quantity: string; reference: string; reason: string; order_id: string; supplier_id: string;
  owner_id: string; item_id: string; unit: string; current: boolean; remaining_paid_quantity: string; remaining_bonus_quantity: string;
  remaining_physical_quantity: string; rejected_quantity: string; reliable_for_planning: boolean; conflicts: string[];
}
export const DELIVERY_PENDING_PREFIX = "flintplate:delivery-pending:v1:";
export const DELIVERY_PATH = /^\/purchasing\/delivery-confirmations$/;
