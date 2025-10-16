import { BackIcon, DownloadIcon } from './Icons';
import { deleteRfp } from '../app/lib/api';
import { useState } from 'react';
import { RfpDetailRow } from '../app/lib/api';

interface DetailViewProps {
  data: RfpDetailRow;
  onBack: () => void;
  onDownload: () => void;
}

export function DetailView({ data, onBack, onDownload }: DetailViewProps) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const formattedDate = data.processed_at 
    ? new Date(data.processed_at).toLocaleString() 
    : 'Unknown date';

  const onDelete = async () => {
    setError(null);
    const ok = window.confirm('Delete this RFP? This action cannot be undone.');
    if (!ok) return;
    try {
      setDeleting(true);
      await deleteRfp(data.hash);
      onBack();
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to delete');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">RFP Details</h2>
          <p className="text-sm text-gray-400 mt-1">View detailed information about this opportunity</p>
        </div>
        <div className="flex items-center gap-3">
          {data.has_pdf && (
            <button
              onClick={onDownload}
              className="rounded-lg bg-blue-600/80 text-white border border-blue-500/50 px-4 py-2 hover:bg-blue-500/90 hover:border-blue-400/70 active:bg-blue-700/90 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md flex items-center gap-2"
            >
              <DownloadIcon />
              Download PDF
            </button>
          )}

          <button
            onClick={onDelete}
            disabled={deleting}
            className="rounded-lg bg-red-600/80 text-white border border-red-500/50 px-4 py-2 hover:bg-red-500/90 hover:border-red-400/70 active:bg-red-700/90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 backdrop-blur-sm shadow-md flex items-center gap-2"
            title="Delete this RFP"
          >
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
          
          <button
            onClick={onBack}
            className="rounded-lg bg-gray-700/70 text-gray-200 border border-gray-600/50 px-4 py-2 hover:bg-gray-600/70 hover:text-white hover:border-gray-500/70 active:bg-gray-800/80 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md flex items-center gap-2"
          >
            <BackIcon />
            Back to Main
          </button>
        </div>
      </div>

      <div className="bg-gray-800/95 rounded-xl p-6 border border-gray-700/50 shadow-lg z-[1]"> {/* More opaque background */}
        <div className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold text-white">{data.title}</h2>
            <p className="text-sm text-gray-400">Found on {formattedDate}</p>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm text-gray-400">Source</label>
              <p className="text-white">{data.site}</p>
            </div>
            <div>
              <label className="text-sm text-gray-400">URL</label>
              <a 
                href={data.url} 
                target="_blank" 
                rel="noreferrer"
                className="text-blue-400 hover:text-blue-300 underline block"
              >
                {data.url}
              </a>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/60 rounded-xl p-4 border border-red-700/50 text-red-100">
          {error}
        </div>
      )}

      {data.ai_summary && (
        <div className="bg-gray-800/95 rounded-xl p-6 border border-gray-700/50 shadow-lg z-[1]">
          <h3 className="text-lg font-medium text-white mb-4">AI Summary</h3>
          <p className="text-gray-200 whitespace-pre-wrap">{data.ai_summary}</p>
        </div>
      )}

      {data.detail_content && (
        <div className="bg-gray-800/95 rounded-xl p-6 border border-gray-700/50 shadow-lg z-[1]">
          <h3 className="text-lg font-medium text-white mb-4">Full Content</h3>
          <p className="text-gray-200 whitespace-pre-wrap">{data.detail_content}</p>
        </div>
      )}
    </div>
  );
}