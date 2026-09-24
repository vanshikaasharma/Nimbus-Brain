import { useEffect, useState, type FormEvent } from "react";

type InvoiceRow = {
  id: number;
  name: string;
  plan: string;
  period_start: string;
  period_end: string;
  amount_cents: number;
};

type Chunk = {
  doc_path: string;
  section: string;
  body: string;
  score: number;
};

function dollars(cents: number) {
  return (cents / 100).toFixed(2);
}

const DOC_EXAMPLES = [
  "What is the Pro rate limit?",
  "What was Acme’s invoice last month?",
];

const SQL_EXAMPLES = [
  "What was Acme’s invoice last month?",
  "Which customers are on Enterprise?",
];

export default function App() {
  const [apiStatus, setApiStatus] = useState("checking…");
  const [rows, setRows] = useState<InvoiceRow[]>([]);
  const [dbError, setDbError] = useState<string | null>(null);
  const [question, setQuestion] = useState(DOC_EXAMPLES[0]);
  const [pending, setPending] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [askError, setAskError] = useState<string | null>(null);
  const [sqlQuestion, setSqlQuestion] = useState(SQL_EXAMPLES[0]);
  const [sqlPending, setSqlPending] = useState(false);
  const [sqlError, setSqlError] = useState<string | null>(null);
  const [sqlText, setSqlText] = useState<string | null>(null);
  const [sqlExplanation, setSqlExplanation] = useState<string | null>(null);
  const [sqlRows, setSqlRows] = useState<Record<string, unknown>[]>([]);

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

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || pending) return;
    setPending(true);
    setAskError(null);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      if (data.error) {
        setAskError(data.error);
        setAnswer(null);
        setChunks([]);
        return;
      }
      setAnswer(data.answer);
      setChunks(data.chunks ?? []);
    } catch {
      setAskError("Ask failed. Is the API running?");
    } finally {
      setPending(false);
    }
  }

  async function onSql(event: FormEvent) {
    event.preventDefault();
    const text = sqlQuestion.trim();
    if (!text || sqlPending) return;
    setSqlPending(true);
    setSqlError(null);
    try {
      const res = await fetch("/api/sql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      if (data.error) {
        setSqlError(data.error);
        setSqlText(data.sql ?? null);
        setSqlExplanation(null);
        setSqlRows([]);
        return;
      }
      setSqlText(data.sql);
      setSqlExplanation(data.explanation);
      setSqlRows(data.rows ?? []);
    } catch {
      setSqlError("SQL ask failed. Is the API running?");
    } finally {
      setSqlPending(false);
    }
  }

  function formatCell(column: string, value: unknown) {
    if (column.includes("amount_cents") && typeof value === "number") {
      return `$${dollars(value)}`;
    }
    if (value === null || value === undefined) return "";
    return String(value);
  }

  return (
    <div className="page">
      <h1>Nimbus Brain</h1>
      <p className="tagline">
        Internal copilot for Nimbus, a fake usage-based API company.
      </p>
      <p>
        Checkpoint 4: docs search and SQL are two separate buttons. Same
        invoice question fails on docs and works on tables.
      </p>
      <p className="status">
        API status: <strong>{apiStatus}</strong>
      </p>

      <h2>Ask the docs</h2>
      <form className="ask" onSubmit={onAsk}>
        <textarea
          rows={3}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={pending}
        />
        <div className="ask-actions">
          {DOC_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="ghost"
              onClick={() => setQuestion(example)}
            >
              {example}
            </button>
          ))}
          <button type="submit" disabled={pending || !question.trim()}>
            {pending ? "Searching…" : "Ask"}
          </button>
        </div>
      </form>
      {askError && <p className="error">{askError}</p>}
      {answer && <p className="answer">{answer}</p>}
      {chunks.length > 0 && (
        <ul className="chunks">
          {chunks.map((chunk) => (
            <li key={`${chunk.doc_path}-${chunk.section}`}>
              <code>
                {chunk.doc_path} &gt; {chunk.section}
              </code>
              <span className="score">score {chunk.score.toFixed(3)}</span>
              <pre>{chunk.body}</pre>
            </li>
          ))}
        </ul>
      )}

      <h2>Ask the tables</h2>
      <p className="hint">
        This hits Neon with a guarded SELECT. It does not search markdown.
      </p>
      <form className="ask" onSubmit={onSql}>
        <textarea
          rows={3}
          value={sqlQuestion}
          onChange={(e) => setSqlQuestion(e.target.value)}
          disabled={sqlPending}
        />
        <div className="ask-actions">
          {SQL_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="ghost"
              onClick={() => setSqlQuestion(example)}
            >
              {example}
            </button>
          ))}
          <button type="submit" disabled={sqlPending || !sqlQuestion.trim()}>
            {sqlPending ? "Querying…" : "Run SQL"}
          </button>
        </div>
      </form>
      {sqlError && <p className="error">{sqlError}</p>}
      {sqlExplanation && <p className="hint">{sqlExplanation}</p>}
      {sqlText && <pre className="sql">{sqlText}</pre>}
      {sqlRows.length > 0 && (
        <table>
          <thead>
            <tr>
              {Object.keys(sqlRows[0]).map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sqlRows.map((row, index) => (
              <tr key={index}>
                {Object.keys(sqlRows[0]).map((col) => (
                  <td key={col}>{formatCell(col, row[col])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Seeded invoices (SQL, not RAG)</h2>
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
