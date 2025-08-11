import { useEffect, useState } from 'react';
import { getSchedule, triggerScrape, listRfps } from '../lib/api';

export default function Home() {
  const [schedule, setSchedule] = useState<any>(null);
  const [rfps, setRfps] = useState<any[]>([]);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    getSchedule().then(res => setSchedule(res.data));
    listRfps().then(res => setRfps(res.data));
  }, []);

  const handleRunNow = async () => {
    setRunning(true);
    const res = await triggerScrape(false, true); // instant, debug only
    alert(`Ran scrape, found ${res.data.new_count} new RFPs`);
    setRunning(false);
  };

  return (
    <div style={{ padding: 24 }}>
      <h1>SmartMatch Admin</h1>
      <section>
        <h2>Schedule</h2>
        <pre>{JSON.stringify(schedule, null, 2)}</pre>
      </section>
      <section>
        <h2>Processed RFPs</h2>
        <ul>
          {rfps.map(r => (
            <li key={r.hash}>
              {r.site}: {r.title} — <a href={r.url}>{r.url}</a> ({r.processed_at})
            </li>
          ))}
        </ul>
      </section>
      <button onClick={handleRunNow} disabled={running}>
        {running ? 'Running...' : 'Run Now (no main email)'}
      </button>
    </div>
  );
}
