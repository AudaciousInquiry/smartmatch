import { useState } from "react";

export interface EmailSettings {
  main_recipients: string[];
  debug_recipients: string[];
}

interface MailingListCardProps {
  initial: EmailSettings;
  onClose: () => void;
  onSave: (settings: EmailSettings) => Promise<void> | void;
}

export function MailingListCard({ initial, onClose, onSave }: MailingListCardProps) {
  const [mainList, setMainList] = useState<string[]>(initial.main_recipients || []);
  const [debugList, setDebugList] = useState<string[]>(initial.debug_recipients || []);
  const [mainInput, setMainInput] = useState("");
  const [debugInput, setDebugInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEmail = (val: string) => /.+@.+\..+/.test(val);

  const addTo = (which: "main" | "debug") => {
    setError(null);
    const val = (which === "main" ? mainInput : debugInput).trim();
    if (!val) return;
    if (!isEmail(val)) {
      setError("Please enter a valid email address.");
      return;
    }
    if (which === "main") {
      if (!mainList.includes(val)) setMainList([...mainList, val]);
      setMainInput("");
    } else {
      if (!debugList.includes(val)) setDebugList([...debugList, val]);
      setDebugInput("");
    }
  };

  const removeFrom = (which: "main" | "debug", val: string) => {
    if (which === "main") setMainList(mainList.filter((x) => x !== val));
    else setDebugList(debugList.filter((x) => x !== val));
  };

  const save = async () => {
    try {
      setSaving(true);
      setError(null);
      await onSave({ main_recipients: mainList, debug_recipients: debugList });
      onClose();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const list = (items: string[], which: "main" | "debug") => (
    <div className="space-y-2">
      {items.length === 0 && (
        <div className="text-sm text-gray-400">No emails added.</div>
      )}
      {items.map((e) => (
        <div key={e} className="w-full flex items-center justify-between bg-gray-700/50 border border-gray-600/40 rounded-lg px-3 py-2">
          <span className="text-gray-100 text-sm">{e}</span>
          <button
            onClick={() => removeFrom(which, e)}
            className="text-xs px-2 py-1 rounded bg-red-600/70 text-white hover:bg-red-500/80"
          >
            Remove
          </button>
        </div>
      ))}
    </div>
  );

  return (
    <div className="w-[730px] bg-gray-800/95 rounded-xl border border-gray-700/50 shadow-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-white">Mailing Lists</h3>
        <button onClick={onClose} className="text-gray-300 hover:text-white">×</button>
      </div>

      {error && (
        <div className="bg-red-900/60 text-red-100 border border-red-700/50 rounded-lg px-3 py-2 text-sm">{error}</div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <h4 className="text-sm font-medium text-white mb-2">Main recipients</h4>
          <div className="flex items-center gap-2 mb-2">
            <input
              value={mainInput}
              onChange={(e) => setMainInput(e.target.value)}
              placeholder="name@example.com"
              className="flex-1 rounded bg-gray-700/60 text-gray-200 placeholder-gray-400 border border-gray-600/50 px-3 py-2"
            />
            <button onClick={() => addTo("main")} className="rounded bg-blue-600/80 text-white px-3 py-2 hover:bg-blue-500/90">Add</button>
          </div>
          {list(mainList, "main")}
        </div>

        <div>
          <h4 className="text-sm font-medium text-white mb-2">Debug recipients</h4>
          <div className="flex items-center gap-2 mb-2">
            <input
              value={debugInput}
              onChange={(e) => setDebugInput(e.target.value)}
              placeholder="name@example.com"
              className="flex-1 rounded bg-gray-700/60 text-gray-200 placeholder-gray-400 border border-gray-600/50 px-3 py-2"
            />
            <button onClick={() => addTo("debug")} className="rounded bg-blue-600/80 text-white px-3 py-2 hover:bg-blue-500/90">Add</button>
          </div>
          {list(debugList, "debug")}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 pt-2">
        <button onClick={onClose} className="rounded bg-gray-700/70 text-gray-100 px-3 py-2 hover:bg-gray-600/70">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded bg-green-600/80 text-white px-4 py-2 hover:bg-green-500/90 disabled:opacity-60">
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
