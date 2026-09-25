import type { Chunk } from "./types";

type Props = {
  route: string | null;
  reason: string | null;
  retried: boolean;
  chunks: Chunk[];
  sql: string | null;
  rows: Record<string, unknown>[];
  paths: string[];
  traceId: string | null;
};

function dollars(cents: number) {
  return (cents / 100).toFixed(2);
}

function formatCell(column: string, value: unknown) {
  if (column.includes("amount_cents") && typeof value === "number") {
    return `$${dollars(value)}`;
  }
  if (value === null || value === undefined) return "";
  return String(value);
}

export function Inspector({ route, reason, retried, chunks, sql, rows, paths, traceId }: Props) {
  return (
    <aside className="inspector">
      <h2>Evidence</h2>
      <p className="hint">Route, passages, SQL, and graph path for the last question.</p>

      <h3>Route</h3>
      {route ? (
        <p className="status">
          <strong>{route}</strong>
          {reason ? ` — ${reason}` : ""}
        </p>
      ) : (
        <p className="hint">Ask a question to see which tool was chosen.</p>
      )}
      {retried && (
        <p className="hint">Retried once after the first passages did not support the question.</p>
      )}

      <h3>Docs</h3>
      {chunks.length === 0 && <p className="hint">No passages for this question.</p>}
      {chunks.length > 0 && (
        <ul className="chunks">
          {chunks.map((chunk) => (
            <li key={`${chunk.doc_path}-${chunk.section}`}>
              <code>
                {chunk.doc_path} &gt; {chunk.section}
              </code>
              <pre>{chunk.body}</pre>
            </li>
          ))}
        </ul>
      )}

      <h3>SQL</h3>
      {!sql && rows.length === 0 && <p className="hint">No query for this question.</p>}
      {sql && <pre className="sql">{sql}</pre>}
      {rows.length > 0 && (
        <table>
          <thead>
            <tr>
              {Object.keys(rows[0]).map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {Object.keys(rows[0]).map((col) => (
                  <td key={col}>{formatCell(col, row[col])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Phoenix</h3>
      {traceId ? (
        <p>
          <a href="http://localhost:6006" target="_blank" rel="noreferrer">
            localhost:6006
          </a>
          <br />
          <code>{traceId}</code>
        </p>
      ) : (
        <p className="hint">No trace yet. Start Phoenix with phoenix serve.</p>
      )}

      <h3>Graph</h3>
      {paths.length === 0 && <p className="hint">No path for this question.</p>}
      {paths.length > 0 && (
        <ul className="paths">
          {paths.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      )}
    </aside>
  );
}
