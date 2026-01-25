import { useState } from "react";

const API_BASE = "http://localhost:9001";

export default function HelloWorldPage() {
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  async function ping() {
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/api/addons/hello_world/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e: any) {
      setErr(String(e));
    }
  }

  return (
    <div>
      <h1 style={{ marginTop: 0 }}>Hello World</h1>
      <p>This page lives in the addon frontend, routed via Core.</p>

      <button
        onClick={ping}
        style={{
          padding: "10px 12px",
          borderRadius: 12,
          border: "1px solid rgba(255,255,255,0.15)",
          background: "rgba(255,255,255,0.06)",
          color: "white",
          cursor: "pointer",
        }}
      >
        Fetch backend status
      </button>

      {err && (
        <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>
          {err}
        </pre>
      )}

      {result && (
        <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}
