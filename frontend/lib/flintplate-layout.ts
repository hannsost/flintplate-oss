export const LAYOUT_PATHS = /^\/(tables\/[a-f0-9-]+\/position|layout\/profiles(?:\/[a-f0-9-]+\/(apply|archive))?)$/;
export interface LayoutPosition { table_id: string; version: number; x: number; y: number; room_id: string | null; area: string }
export interface LayoutProfile { id: string; name: string; room_id: string | null; version: number; archived: boolean; current_revision_id: string; table_count: number; created_at: string; updated_at: string }
export interface LayoutRevision { id: string; profile_id: string; previous_id: string | null; version: number; name: string; room_id: string | null; archived: boolean; placements: LayoutPosition[]; actor_id: string; created_at: string }
export interface LayoutPreview {
  profile_id: string; profile_version: number; revision_id: string; snapshot_version: number; name: string; room_id: string | null;
  rows: { table_id: string; name: string; current: LayoutPosition | null; saved: LayoutPosition; changed: boolean }[];
  added_table_ids: string[]; missing_table_ids: string[]; blocking_reasons: string[]; fingerprint: string;
}
