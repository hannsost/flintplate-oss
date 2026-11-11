import { request } from "./api";
export interface PlanningWorker { id: string; name: string; skills: string[] }
export interface Demand { key: string; title: string; headcount: number; required_skills: string[] }
export interface Trip { key: string; demand_key: string; pickup: string; vehicle: string; seats: number; outbound_minutes: number; return_minutes: number; source: string }
export interface PlanInput {
  title: string; time_zone: string; shift_start: string; shift_end: string; arrival_buffer_minutes: number;
  demands: Demand[]; trips: Trip[];
  workers: { worker_id: string; pickup: string; available_from: string; available_until: string; max_commute_minutes: number }[];
}
export interface MobilityPlan { id: string; title: string; created_at: string; inputs: PlanInput; result: {
  allocations: { worker_id: string; worker_name: string; demand_key: string; trip_key: string; departure: string; return_arrival: string; travel_minutes: number; matched_skills: string[] }[];
  demands: { key: string; title: string; requested: number; allocated: number; unfilled: number }[];
  unassigned: { worker_id: string; reason: string }[]; total_travel_minutes: number; method: string; limitations: string[];
} }
export const mobilityApi = {
  workers: (t: string) => request<PlanningWorker[]>("/mobility/workers", {}, t),
  plans: (t: string) => request<MobilityPlan[]>("/mobility/plans", {}, t),
  create: (t: string, d: PlanInput) => request<MobilityPlan>("/mobility/plans", { method: "POST", body: JSON.stringify(d) }, t),
};
