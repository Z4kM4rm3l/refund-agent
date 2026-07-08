// Dropdown of seeded CRM profiles. The backend doesn't label scenario types,
// so we derive a human-readable label per order — first from a fixed lookup
// matching backend/db/seed.py's known demo order numbers, falling back to a
// heuristic derived from the order's own fields for anything unrecognized.

const KNOWN_SCENARIOS = {
  "MMX-10001": "Clean Approval",
  "MMX-10002": "Clean Approval",
  "MMX-10003": "Clean Approval",
  "MMX-10004": "Clean Approval",
  "MMX-10005": "Clean Approval",
  "MMX-10006": "Software Denial",
  "MMX-10007": "Opened Amp Denial",
  "MMX-10008": "Used/Vintage Denial",
  "MMX-10009": "Damaged Book Denial",
  "MMX-10010": "High-Value Escalation",
  "MMX-10011": "Missing Receipt Escalation",
  "MMX-10012": "Ambiguous Condition Escalation",
  "MMX-10013": "Holiday Extension Wildcard",
  "MMX-10014": "Missing Receipt Wildcard",
  "MMX-10015": "Split Eligibility (Bundle)",
};

function deriveScenarioLabel(order) {
  if (!order) return "No Orders";
  if (KNOWN_SCENARIOS[order.order_number]) return KNOWN_SCENARIOS[order.order_number];

  if (order.is_bundle) return "Split Eligibility (Bundle)";
  if (order.category === "Software & Digital Downloads") return "Software Denial";
  if (!order.has_receipt) return "Missing Receipt";
  if (order.price >= 500) return "High-Value Escalation";
  if (order.is_holiday_purchase) return "Holiday Wildcard";
  if (order.condition === "unopened") return "Clean Approval";
  return "Denial";
}

export default function CustomerSelector({ customers, selectedCustomerId, onSelect }) {
  const selected = customers.find((c) => c.id === selectedCustomerId);
  const primaryOrder = selected?.orders?.[0];

  return (
    <div className="customer-selector">
      <label htmlFor="customer-select">Select Customer</label>
      <select
        id="customer-select"
        value={selectedCustomerId ?? ""}
        onChange={(e) => {
          const id = Number(e.target.value);
          const customer = customers.find((c) => c.id === id);
          onSelect(customer ?? null);
        }}
      >
        <option value="" disabled>
          — choose a demo customer —
        </option>
        {customers.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} — {deriveScenarioLabel(c.orders?.[0])}
          </option>
        ))}
      </select>

      {selected && primaryOrder && (
        <div className="customer-selector__meta">
          <span>
            <strong>Order:</strong> {primaryOrder.order_number}
          </span>
          <span>
            <strong>Item:</strong> {primaryOrder.product_name}
          </span>
          <span>
            <strong>Price:</strong> ${primaryOrder.price?.toFixed(2)}
          </span>
        </div>
      )}
    </div>
  );
}

export { deriveScenarioLabel };
