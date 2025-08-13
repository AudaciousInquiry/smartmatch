import axios from "axios";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000",
});

export type RfpRow = {
  hash: string;
  title: string;
  url: string;
  site: string;
  processed_at: string | null;
};

export const listRfps = (params?: { q?: string; limit?: number; offset?: number; sort?: string; order?: "asc" | "desc" }) =>
  api.get<RfpRow[]>("/rfps", { params });

export const getSchedule = () => api.get("/schedule");
export const updateSchedule = (data: { enabled: boolean; interval_hours: number }) =>
  api.put("/schedule", data);

export const getEmailSettings = () => api.get("/email-settings");
export const setEmailSettings = (data: { main_recipients: string[]; debug_recipients: string[] }) =>
  api.put("/email-settings", data);

export const triggerScrape = (send_main: boolean, send_debug: boolean) =>
  api.post("/scrape", null, { params: { send_main, send_debug } });
