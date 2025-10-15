"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getRfpDetail, downloadPdf, type RfpDetailRow } from "../app/lib/api";
import { DetailView } from "./DetailView";
import { Notification, NotificationType } from "./Notification";
import { createPortal } from "react-dom";

interface RfpDetailContainerProps {
  hash: string;
}

export function RfpDetailContainer({ hash }: RfpDetailContainerProps) {
  const router = useRouter();
  const [data, setData] = useState<RfpDetailRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [notification, setNotification] = useState<{ message: string; type: NotificationType } | null>(null);

  const showNotification = (message: string, type: NotificationType) => {
    setNotification({ message, type });
  };

  useEffect(() => {
    const loadDetail = async () => {
      setLoading(true);
      try {
        const res = await getRfpDetail(hash);
        setData(res.data);
      } catch (error) {
        showNotification('Failed to load RFP details', 'error');
        // Redirect back to list after showing error
        setTimeout(() => router.push('/'), 2000);
      } finally {
        setLoading(false);
      }
    };

    loadDetail();
  }, [hash, router]);

  const handleDownloadPdf = async () => {
    if (!data) return;
    
    try {
      const res = await downloadPdf(data.hash);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${data.title}.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      showNotification('PDF downloaded successfully', 'success');
    } catch (error) {
      showNotification('Failed to download PDF', 'error');
    }
  };

  const handleBack = () => {
    router.push('/');
  };

  // Determine content based on state
  let content: React.ReactNode;
  
  if (loading) {
    content = <div className="text-white text-xl">Loading RFP details...</div>;
  } else if (!data) {
    content = <div className="text-white text-xl">RFP not found</div>;
  } else {
    content = (
      <DetailView 
        data={data}
        onBack={handleBack}
        onDownload={handleDownloadPdf}
      />
    );
  }

  return (
    <>
      {notification && createPortal(
        <Notification
          message={notification.message}
          type={notification.type}
          onClose={() => setNotification(null)}
        />,
        document.body
      )}
      <div className={loading || !data ? "flex items-center justify-center min-h-[calc(100vh-3rem)]" : ""}>
        {content}
      </div>
    </>
  );
}
