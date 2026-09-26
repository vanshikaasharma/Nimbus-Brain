import { useEffect, useState, type FormEvent } from "react";
import { Inspector } from "./Inspector";
import type { Chunk } from "./types";

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

const DOC_EXAMPLES = [
  "What is the Pro rate limit?",
  "What was Acme’s invoice last month?",
];

const SQL_EXAMPLES = [
  "What was Acme’s invoice last month?",
  "Which customers are on Enterprise?",
];

const GRAPH_EXAMPLES = [
  "Which Enterprise customers were on INC-104?",
  "Who was hit by the ingest outage?",
];

const ROUTED_EXAMPLES = [
  { label: "Pro rate limit", question: "What is the Pro rate limit?" },
  { label: "Acme's invoice", question: "What was Acme’s invoice last month?" },
  { label: "INC-104", question: "Which Enterprise customers were on INC-104?" },
  {
    label: "Outage, SLA, and invoice",
    question:
      "Which Enterprise customers were hit by the outage, what does the SLA say we owe them, and how much was the August invoice?",
  },
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
  const [graphQuestion, setGraphQuestion] = useState(GRAPH_EXAMPLES[0]);
  const [graphPending, setGraphPending] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [graphPaths, setGraphPaths] = useState<string[]>([]);
  const [graphTriples, setGraphTriples] = useState<string[]>([]);
  const [graphNote, setGraphNote] = useState<string | null>(null);
  const [routedQuestion, setRoutedQuestion] = useState(ROUTED_EXAMPLES[0].question);
  const [routePending, setRoutePending] = useState(false);
  const [routeMode, setRouteMode] = useState<"chat" | "agent">("chat");
  const [routeError, setRouteError] = useState<string | null>(null);
  const [routeName, setRouteName] = useState<string | null>(null);
  const [routeReason, setRouteReason] = useState<string | null>(null);
  const [routeAnswer, setRouteAnswer] = useState<string | null>(null);
  const [routeChunks, setRouteChunks] = useState<Chunk[]>([]);
  const [routeSql, setRouteSql] = useState<string | null>(null);
  const [routeSqlRows, setRouteSqlRows] = useState<Record<string, unknown>[]>([]);
  const [routePaths, setRoutePaths] = useState<string[]>([]);
  const [routeRetried, setRouteRetried] = useState(false);
  const [routeTraceId, setRouteTraceId] = useState<string | null>(null);

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

  async function askRouted(mode: "chat" | "agent") {
    const text = routedQuestion.trim();
    if (!text || routePending) return;
    setRouteMode(mode);
    setRoutePending(true);
    setRouteError(null);
    setRouteName(null);
    setRouteReason(null);
    setRouteAnswer(null);
    setRouteChunks([]);
    setRouteSql(null);
    setRouteSqlRows([]);
    setRoutePaths([]);
    setRouteRetried(false);
    setRouteTraceId(null);
    try {
      const res = await fetch(mode === "agent" ? "/api/agent" : "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      if (data.error && !data.route) {
        setRouteError(data.error);
        return;
      }
      setRouteName(data.route ?? null);
      setRouteReason(data.reason ?? null);
      setRouteAnswer(data.answer ?? null);
      setRouteChunks(data.chunks ?? []);
      if (data.sql?.error) {
        setRouteError(data.sql.error);
      }
      setRouteSql(data.sql?.sql ?? null);
      setRouteSqlRows(data.sql?.rows ?? []);
      if (data.graph?.error) {
        setRouteError(data.graph.error);
      }
      setRoutePaths(data.graph?.paths ?? []);
      setRouteRetried(Boolean(data.retried));
      setRouteTraceId(data.phoenix_trace_id ?? null);
    } catch {
      setRouteError("Chat failed. Is the API running?");
    } finally {
      setRoutePending(false);
    }
  }

  async function onGraph(event: FormEvent) {
    event.preventDefault();
    const text = graphQuestion.trim();
    if (!text || graphPending) return;
    setGraphPending(true);
    setGraphError(null);
    setGraphNote(null);
    try {
      const res = await fetch("/api/graph", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      if (data.error) {
        setGraphError(data.error);
        setGraphPaths([]);
        setGraphTriples([]);
        setGraphNote(data.explanation ?? null);
        return;
      }
      setGraphPaths(data.paths ?? []);
      setGraphTriples(data.triples ?? []);
      setGraphNote(data.explanation ?? null);
    } catch {
      setGraphError("Graph ask failed. Is the API running?");
    } finally {
      setGraphPending(false);
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
        Ask about pricing, an invoice, or the INC-104 outage. The panel on the right is the evidence.
      </p>
      {apiStatus !== "connected" && (
        <p className="status">
          API status: <strong>{apiStatus}</strong>
        </p>
      )}

      <div className="workspace">
        <section>
          <h2>Ask</h2>
          <form
            className="ask"
            onSubmit={(event) => {
              event.preventDefault();
              void askRouted("chat");
            }}
          >
            <textarea
              rows={3}
              value={routedQuestion}
              onChange={(e) => setRoutedQuestion(e.target.value)}
              disabled={routePending}
            />
            <div className="examples">
              {ROUTED_EXAMPLES.map((example) => (
                <button
                  key={example.label}
                  type="button"
                  className="ghost"
                  onClick={() => setRoutedQuestion(example.question)}
                >
                  {example.label}
                </button>
              ))}
            </div>
            <div className="ask-actions">
              <button type="submit" disabled={routePending || !routedQuestion.trim()}>
                {routePending && routeMode === "chat" ? "Routing…" : "Ask"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={routePending || !routedQuestion.trim()}
                onClick={() => void askRouted("agent")}
              >
                {routePending && routeMode === "agent" ? "Choosing tools…" : "Ask with the loop"}
              </button>
            </div>
          </form>
          {routeError && <p className="error">{routeError}</p>}
          {routeAnswer && <p className="answer">{routeAnswer}</p>}
        </section>
        <Inspector
          route={routeName}
          reason={routeReason}
          retried={routeRetried}
          chunks={routeChunks}
          sql={routeSql}
          rows={routeSqlRows}
          paths={routePaths}
          traceId={routeTraceId}
        />
      </div>

      <details className="lab">
        <summary>Call a tool yourself</summary>
        <p className="hint">
          Docs, SQL, the graph, and the seeded invoices. The question box above already picks one of these.
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
            <li key={chunk.source_id ?? `${chunk.doc_path}-${chunk.section}`}>
              <code>
                {chunk.source_id ?? chunk.doc_path}
                {chunk.page_number ? ` p.${chunk.page_number}` : ""} &gt; {chunk.section}
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

      <h2>Ask the graph</h2>
      <p className="hint">
        The model names a one-hop or two-hop plan. The server checks it, then reads nodes and edges.
      </p>
      <form className="ask" onSubmit={onGraph}>
        <textarea
          rows={3}
          value={graphQuestion}
          onChange={(e) => setGraphQuestion(e.target.value)}
          disabled={graphPending}
        />
        <div className="ask-actions">
          {GRAPH_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="ghost"
              onClick={() => setGraphQuestion(example)}
            >
              {example}
            </button>
          ))}
          <button type="submit" disabled={graphPending || !graphQuestion.trim()}>
            {graphPending ? "Walking…" : "Walk graph"}
          </button>
        </div>
      </form>
      {graphError && <p className="error">{graphError}</p>}
      {graphNote && <p className="hint">{graphNote}</p>}
      {graphPaths.length > 0 && (
        <ul className="paths">
          {graphPaths.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      )}
      {graphTriples.length > 0 && (
        <ul className="chunks">
          {graphTriples.map((triple) => (
            <li key={triple}>
              <code>{triple}</code>
            </li>
          ))}
        </ul>
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
      </details>
    </div>
  );
}
