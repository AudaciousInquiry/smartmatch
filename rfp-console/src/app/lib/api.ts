import axios from 'axios';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000",
});

export const listRfps = (params?: { q?: string; limit?: number; offset?: number; sort?: string; order?: "asc" | "desc" }) =>
  api.get<RfpRow[]>("/rfps", { params });

export const getSchedule = async () => {
  try {
    return await api.get("/schedule");
  } catch (e: any) {
    if (e?.response?.status === 404) {
      // Gracefully handle no schedule set
      return { data: null };
    }
    throw e;
  }
};
export const updateSchedule = (data: {
  enabled: boolean;
  interval_hours: number;
  next_run_hour: number;
  next_run_minute: number;
}) => api.put("/schedule", data);

export const clearSchedule = () => api.delete("/schedule");

export const getEmailSettings = () => api.get("/email-settings");
export const setEmailSettings = (data: { main_recipients: string[]; debug_recipients: string[] }) =>
  api.put("/email-settings", data);

export const triggerScrape = (send_main: boolean, send_debug: boolean) =>
  api.post("/scrape", null, { params: { send_main, send_debug } });

export const getRfpDetail = (hash: string) => 
  api.get<RfpDetailRow>(`/rfps/${hash}`);

export const downloadPdf = (hash: string) =>
  api.get(`/rfps/${hash}/pdf`, { responseType: 'blob' });

export const deleteRfp = (hash: string) =>
  api.delete(`/rfps/${hash}`);

export type RfpRow = {
  hash: string;
  title: string;
  url: string;
  site: string;
  processed_at: string;
};

export type RfpDetailRow = RfpRow & {
  detail_content: string | null;
  ai_summary: string | null;
  has_pdf: boolean;
};
