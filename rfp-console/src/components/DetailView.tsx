import { BackIcon, DownloadIcon } from './Icons';
import { RfpDetailRow } from '../app/lib/api';

interface DetailViewProps {
  data: RfpDetailRow;
  onBack: () => void;
  onDownload: () => void;
}

export function DetailView({ data, onBack, onDownload }: DetailViewProps) {
  const formattedDate = data.processed_at 
    ? new Date(data.processed_at).toLocaleString() 
    : 'Unknown date';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between z-[1000]"> {/* Buttons above cards but below schedule */}
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded-lg bg-gray-600/70 text-gray-200 border border-gray-500/50 px-3 py-3 hover:bg-gray-500/60 hover:text-white hover:border-gray-400/50 active:bg-gray-700/70 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md flex items-center gap-2"
          >
            <BackIcon />
            Back to List
          </button>
          
          {data.has_pdf && (
            <button
              onClick={onDownload}
              className="rounded-lg bg-blue-600/70 text-gray-200 border border-blue-500/50 px-3 py-3 hover:bg-blue-500/60 hover:text-white hover:border-blue-400/50 active:bg-blue-700/70 active:scale-95 transition-all duration-200 backdrop-blur-sm shadow-md flex items-center gap-2"
            >
              <DownloadIcon />
              Download PDF
            </button>
          )}
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