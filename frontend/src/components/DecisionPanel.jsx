const STATUS_LABELS = {
  approved: "Approved",
  denied: "Denied",
  escalated: "Escalated",
  split: "Split",
  info: "Info",
  needs_identification: "Needs Info",
  gathering_order: "Awaiting Order",
  gathering_reason: "Awaiting Reason",
  pending: "Pending",
};

export default function DecisionPanel({ status, decision, customer, order }) {
  const hasDecision = Boolean(decision);
  const effectiveStatus = decision?.status ?? status;
  const badgeClass = `status-badge status-badge--lg status-badge--${effectiveStatus ?? "pending"}`;

  return (
    <div className="decision-panel rack-panel">
      <div className="decision-panel__header">
        <span className="section-header__label" style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--accent-amber)", textTransform: "uppercase", letterSpacing: "0.12em" }}>
          Decision Panel
        </span>
        <span className={badgeClass}>{STATUS_LABELS[effectiveStatus] ?? effectiveStatus ?? "—"}</span>
      </div>

      {!effectiveStatus && (
        <div className="decision-panel__empty">No refund decision yet for this session — send a message to begin.</div>
      )}

      {(customer || order) && (
        <div className="decision-panel__grid">
          <div className="decision-field">
            <label>Customer</label>
            <div>{customer?.name ?? "—"}</div>
          </div>
          <div className="decision-field">
            <label>Order</label>
            <div>{order?.order_number ?? "—"}</div>
          </div>
          <div className="decision-field">
            <label>Item</label>
            <div>{order?.product_name ?? "—"}</div>
          </div>
          <div className="decision-field">
            <label>Amount</label>
            <div>{typeof order?.price === "number" ? `$${order.price.toFixed(2)}` : "—"}</div>
          </div>
        </div>
      )}

      {hasDecision && decision.decision_summary && (
        <div className="decision-panel__reasoning">
          <label>Decision Summary</label>
          <p>{decision.decision_summary}</p>
        </div>
      )}

      {hasDecision && decision.policy_reasoning && (
        <div className="decision-panel__reasoning">
          <label>Policy Rule Applied</label>
          <p>{decision.policy_reasoning}</p>
        </div>
      )}

      {hasDecision && decision.escalation_reason && (
        <div className="decision-panel__escalation">⚠ Escalation: {decision.escalation_reason}</div>
      )}
    </div>
  );
}
