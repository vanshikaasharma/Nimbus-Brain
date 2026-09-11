import { useEffect, useState } from "react";

export default function App() {
  const [apiStatus, setApiStatus] = useState("checking…");

  useEffect(() => {
    fetch("/api/health")
      .then((res) => res.json())
      .then((data) => setApiStatus(data.status === "ok" ? "connected" : "unexpected response"))
      .catch(() => setApiStatus("offline — start the FastAPI server"));
  }, []);

  return (
    <div className="page">
      <h1>Nimbus Brain</h1>
      <p className="tagline">
        Internal copilot for Nimbus, a fake usage-based API company.
      </p>
      <p>
        Right now this is just the project box: a frontend and an API that
        can see each other. No docs, no database, no answers yet.
      </p>
      <p className="status">
        API status: <strong>{apiStatus}</strong>
      </p>
    </div>
  );
}
