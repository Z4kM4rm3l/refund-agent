import ReasoningLog from "./ReasoningLog.jsx";
import DecisionPanel from "./DecisionPanel.jsx";

function groupByAgent(entries, agentName) {
  return entries.filter((e) => e.agent === agentName);
}

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour12: false });
  } catch {
    return ts ?? "—";
  }
}

export default function AdminDashboard({ reasoningEntries, decision, status, customer, order, sessionLog }) {
  const orchestratorEntries = groupByAgent(reasoningEntries, "Orchestrator");
  const validatorEntries = groupByAgent(reasoningEntries, "Policy Validator");
  const resolverEntries = groupByAgent(reasoningEntries, "Refund Resolver");

  return (
    <div className="admin-dashboard">
      <div className="admin-header">
        <div className="admin-header__title">
          <span style={{ color: "var(--border-light)" }}>// </span>
          AGENT REASONING <span>CONSOLE</span>
          <span style={{ color: "var(--border-light)" }}> //</span>
        </div>
        <div className="live-indicator">
          <span className="led" />
          LIVE
        </div>
      </div>

      <div className="admin-body">
        <div className="agent-lanes">
          <ReasoningLog laneKey="orchestrator" agentLabel="Orchestrator" entries={orchestratorEntries} />
          <ReasoningLog laneKey="validator" agentLabel="Policy Validator" entries={validatorEntries} />
          <ReasoningLog laneKey="resolver" agentLabel="Refund Resolver" entries={resolverEntries} />
        </div>

        <DecisionPanel status={status} decision={decision} customer={customer} order={order} />

        <div className="session-log">
          <div className="session-log__header">
            <span>Full Session Log — Setlist</span>
            <span>{sessionLog.length} entries</span>
          </div>
          {sessionLog.length === 0 ? (
            <div className="session-log__empty">No decisions recorded yet this session.</div>
          ) : (
            <div className="session-log__scroll">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Customer</th>
                    <th>Product</th>
                    <th>Decision</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {sessionLog.map((row, idx) => (
                    <tr key={row.id}>
                      <td className="track-number">{String(idx + 1).padStart(2, "0")}</td>
                      <td>{row.customerName}</td>
                      <td>{row.productName}</td>
                      <td>
                        <span className={`status-badge status-badge--${row.status}`}>{row.status}</span>
                      </td>
                      <td className="track-number">{formatTimestamp(row.timestamp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
