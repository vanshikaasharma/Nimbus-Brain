import { useEffect, useState } from "react";

type InvoiceRow = {
  id: number;
  name: string;
  plan: string;
  period_start: string;
  period_end: string;
  amount_cents: number;
};

function dollars(cents: number) {
  return (cents / 100).toFixed(2);
}

export default function App() {
  const [apiStatus, setApiStatus] = useState("checking…");
  const [rows, setRows] = useState<InvoiceRow[]>([]);
  const [dbError, setDbError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((res) => res.json())
      .then((data) => setApiStatus(data.status === "ok" ? "connected" : "unexpected response"))
      .catch(() => setApiStatus("offline — start the FastAPI server"));

    fetch("/api/customers")
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setDbError(data.error);
          return;
        }
        setRows(data.customers ?? []);
      })
      .catch(() => setDbError("Could not load customers"));
  }, []);

  return (
    <div className="page">
      <h1>Nimbus Brain</h1>
      <p className="tagline">
        Internal copilot for Nimbus, a fake usage-based API company.
      </p>
      <p>
        Checkpoint 2: a few docs in <code>corpus/</code> and a tiny customer /
        invoice world in Postgres. Still no chatbot.
      </p>
      <p className="status">
        API status: <strong>{apiStatus}</strong>
      </p>

      <h2>Seeded invoices</h2>
      {dbError && <p className="error">{dbError}</p>}
      {!dbError && rows.length === 0 && <p>No rows yet. Run the seed script.</p>}
      {rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Customer</th>
              <th>Plan</th>
              <th>Period</th>
              <th>Invoice</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.id}-${row.period_start}`}>
                <td>{row.name}</td>
                <td>{row.plan}</td>
                <td>
                  {row.period_start} → {row.period_end}
                </td>
                <td>${dollars(row.amount_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
