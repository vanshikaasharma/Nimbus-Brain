import type { Chunk } from "./types";

type Retry = {
  tool: string;
  reason: string;
};

type Props = {
  route: string | null;
  reason: string | null;
  retried: boolean;
  tools: string[];
  retries: Retry[];
  missing: string[];
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

export function Inspector({
  route,
  reason,
  retried,
  tools,
  retries,
  missing,
  chunks,
  sql,
  rows,
  paths,
  traceId,
}: Props) {
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
      {tools.length > 0 && (
        <p className="hint">Tools: {tools.join(", ")}</p>
      )}
      {retries.map((retry) => (
        <p className="hint" key={`${retry.tool}-${retry.reason}`}>
          Retry ({retry.tool}): {retry.reason}
        </p>
      ))}
      {missing.length > 0 && <p className="hint">Missing: {missing.join(", ")}</p>}
      {retried && retries.length === 0 && (
        <p className="hint">Retried once after the first passages did not support the question.</p>
      )}

      {chunks.length > 0 && (
        <>
          <h3>Docs</h3>
          <ul className="chunks">
            {chunks.map((chunk) => (
              <li key={chunk.source_id ?? `${chunk.doc_path}-${chunk.section}`}>
                <code>
                  {chunk.source_id ?? chunk.doc_path}
                  {chunk.page_number ? ` p.${chunk.page_number}` : ""} &gt; {chunk.section}
                </code>
                <pre>{chunk.body}</pre>
              </li>
            ))}
          </ul>
        </>
      )}

      {(sql || rows.length > 0) && (
        <>
          <h3>SQL</h3>
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
        </>
      )}

      {paths.length > 0 && (
        <>
          <h3>Graph</h3>
          <ul className="paths">
            {paths.map((path) => (
              <li key={path}>{path}</li>
            ))}
          </ul>
        </>
      )}

      {traceId && (
        <>
          <h3>Phoenix</h3>
          <p>
            <a href="http://localhost:6006" target="_blank" rel="noreferrer">
              localhost:6006
            </a>
            <br />
            <code>{traceId}</code>
          </p>
        </>
      )}
    </aside>
  );
}
