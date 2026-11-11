import { request } from "./api";

export interface WorkspaceBranding {
  company_name: string;
  brand_name: string | null;
  slug: string;
  primary_color: string;
  logo_url: string | null;
  version: number;
  can_manage: boolean;
}

export const brandingApi = {
  get: (token: string) => request<WorkspaceBranding>("/companies/workspace/branding", {}, token),
  save: (token: string, data: Pick<WorkspaceBranding, "brand_name" | "primary_color" | "logo_url" | "version">) =>
    request<WorkspaceBranding>("/companies/workspace/branding", { method: "PUT", body: JSON.stringify(data) }, token),
};

/** Keep branded buttons legible for both light and dark tenant colors. */
export function brandTextColor(hex: string): "#000000" | "#ffffff" {
  const channels = [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const [r, g, b] = channels.map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 ? "#000000" : "#ffffff";
}
