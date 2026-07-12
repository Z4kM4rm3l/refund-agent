import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CustomerSelector from "./components/CustomerSelector.jsx";
import ChatInterface from "./components/ChatInterface.jsx";
import AdminDashboard from "./components/AdminDashboard.jsx";
import { fetchAdminLogs, fetchCustomers, streamChatMessage } from "./api.js";

const ADMIN_POLL_INTERVAL_MS = 2000;
const THEME_STORAGE_KEY = "melodymax-theme";

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="12" cy="12" r="4.5" fill="currentColor" />
      {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => (
        <line
          key={deg}
          x1="12"
          y1="2.5"
          x2="12"
          y2="5.5"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          transform={`rotate(${deg} 12 12)`}
        />
      ))}
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" fill="currentColor" />
    </svg>
  );
}

function newConversationId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `conv-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function App() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // localStorage unavailable (private mode etc.) — theme still applies for this session
    }
  }, [theme]);

  const [customers, setCustomers] = useState([]);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [conversationId, setConversationId] = useState(newConversationId());

  const [chatMessages, setChatMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState(null);

  // Reasoning entries from turns already completed in this conversation — the
  // backend's ReasoningLogger starts fresh each turn, so the frontend is
  // responsible for accumulating the full multi-turn trace across a session.
  const reasoningBaseRef = useRef([]);
  const [turnReasoningLog, setTurnReasoningLog] = useState([]);
  const [currentDecision, setCurrentDecision] = useState(null);
  const [currentStatus, setCurrentStatus] = useState(null);
  const [currentOrder, setCurrentOrder] = useState(null);

  // Guards against overlapping handleSend calls (e.g. the customer switch
  // mid-turn, or a race between two sends) applying a stale turn's events
  // on top of a newer one's. Bumped at the start of every handleSend and on
  // customer switch; each in-flight call only applies its state updates
  // while its own id is still the active one.
  const activeRequestIdRef = useRef(0);

  const [adminData, setAdminData] = useState({ refundRequests: [], reasoningLogs: [] });

  // -- initial data load ----------------------------------------------------

  useEffect(() => {
    fetchCustomers()
      .then(setCustomers)
      .catch((err) => console.error("Failed to load customers:", err));
  }, []);

  const refreshAdminLogs = useCallback(() => {
    fetchAdminLogs()
      .then(setAdminData)
      .catch((err) => console.error("Failed to load admin logs:", err));
  }, []);

  useEffect(() => {
    refreshAdminLogs();
    const interval = setInterval(refreshAdminLogs, ADMIN_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refreshAdminLogs]);

  // -- customer switch: start a fresh conversation ---------------------------

  const handleSelectCustomer = (customer) => {
    // Invalidate any in-flight request for the conversation we're leaving —
    // its events must not land on top of the new conversation's state.
    activeRequestIdRef.current += 1;
    setIsSending(false);

    setSelectedCustomer(customer);
    setConversationId(newConversationId());
    setChatMessages([]);
    setStreamingMessageId(null);
    reasoningBaseRef.current = [];
    setTurnReasoningLog([]);
    setCurrentDecision(null);
    setCurrentStatus(null);
    // Don't pre-fill the order here — the agent now discovers it through
    // conversation (see the multi-turn gathering flow), so the Decision
    // Panel should stay empty until a "context" stream event reveals it,
    // same as the agent's own knowledge.
    setCurrentOrder(null);
  };

  // -- sending a chat message (streamed) --------------------------------------

  const handleSend = async (text) => {
    // isSending is the primary guard (also disables the UI — see ChatInterface);
    // requestId is defense-in-depth against anything that still slips through
    // (e.g. a customer switch invalidating this call mid-flight).
    if (!selectedCustomer || isSending) return;

    const requestId = ++activeRequestIdRef.current;
    const isStale = () => requestId !== activeRequestIdRef.current;

    setChatMessages((prev) => [
      ...prev,
      { id: `c-${Date.now()}`, role: "customer", text, timestamp: new Date().toISOString() },
    ]);
    setIsTyping(true);
    setIsSending(true);

    const agentMessageId = `a-${Date.now()}`;
    const reasoningBase = reasoningBaseRef.current;
    let agentBubbleStarted = false;
    let accumulatedReply = "";
    let latestTurnEntries = [];

    try {
      await streamChatMessage(
        { message: text, conversationId, customerId: selectedCustomer.id },
        (event) => {
          if (isStale()) return; // a newer request (or customer switch) has superseded this one

          switch (event.type) {
            case "context":
              if (event.order) setCurrentOrder(event.order);
              break;

            case "reasoning":
              latestTurnEntries = event.entries ?? [];
              setTurnReasoningLog([...reasoningBase, ...latestTurnEntries]);
              break;

            case "reply_delta":
              if (!agentBubbleStarted) {
                agentBubbleStarted = true;
                setIsTyping(false);
                setStreamingMessageId(agentMessageId);
                setChatMessages((prev) => [
                  ...prev,
                  { id: agentMessageId, role: "agent", text: "", timestamp: new Date().toISOString() },
                ]);
              }
              accumulatedReply += event.text;
              setChatMessages((prev) =>
                prev.map((m) => (m.id === agentMessageId ? { ...m, text: accumulatedReply } : m))
              );
              break;

            case "final":
              setCurrentDecision(event.decision ?? null);
              setCurrentStatus(event.status ?? null);
              setStreamingMessageId(null);
              break;

            case "error":
              throw new Error(event.error || "The agent hit an unexpected error.");

            default:
              break;
          }
        }
      );

      if (!isStale()) {
        reasoningBaseRef.current = [...reasoningBase, ...latestTurnEntries];
        // Refresh immediately so the Decision Panel's policy citation shows up
        // without waiting for the next 2s poll tick.
        refreshAdminLogs();
      }
    } catch (err) {
      console.error("Chat request failed:", err);
      if (!isStale()) {
        setStreamingMessageId(null);
        setChatMessages((prev) => [
          ...prev,
          {
            id: `e-${Date.now()}`,
            role: "error",
            text: "Signal lost — the agent console couldn't reach the backend. Is it running on :5000?",
            timestamp: new Date().toISOString(),
          },
        ]);
      }
    } finally {
      if (!isStale()) {
        setIsTyping(false);
        setIsSending(false);
      }
    }
  };

  // -- lookups for enrichment -------------------------------------------------

  const customersById = useMemo(() => {
    const map = new Map();
    customers.forEach((c) => map.set(c.id, c));
    return map;
  }, [customers]);

  const ordersByNumber = useMemo(() => {
    const map = new Map();
    customers.forEach((c) => (c.orders ?? []).forEach((o) => map.set(o.order_number, o)));
    return map;
  }, [customers]);

  const enrichedDecision = useMemo(() => {
    if (!currentDecision) return null;
    const matchedRow = adminData.refundRequests.find((r) => r.id === currentDecision.id);
    if (!matchedRow) return currentDecision;
    return {
      ...currentDecision,
      policy_reasoning: matchedRow.policy_reasoning,
      escalation_reason: matchedRow.escalation_reason,
    };
  }, [currentDecision, adminData.refundRequests]);

  const sessionLog = useMemo(
    () =>
      adminData.refundRequests.map((r) => ({
        id: r.id,
        customerName: customersById.get(r.customer_id)?.name ?? "Unknown",
        productName: ordersByNumber.get(r.order_number)?.product_name ?? r.order_number ?? "—",
        status: r.status,
        timestamp: r.created_at,
      })),
    [adminData.refundRequests, customersById, ordersByNumber]
  );

  return (
    <>
      <div className="app-topbar">
        <span className="app-topbar__logo">
          MELODYMAX<span>GEAR</span>
        </span>
        <span className="app-topbar__sub">// Refund Agent Console</span>
        <button
          type="button"
          className="btn-theme"
          onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>

      <div className="app-shell">
        <div className="panel-left">
          <CustomerSelector
            customers={customers}
            selectedCustomerId={selectedCustomer?.id ?? null}
            onSelect={handleSelectCustomer}
          />
          <ChatInterface
            messages={chatMessages}
            onSend={handleSend}
            isTyping={isTyping}
            disabled={!selectedCustomer}
            isSending={isSending}
            streamingMessageId={streamingMessageId}
          />
        </div>

        <div className="panel-right">
          <AdminDashboard
            reasoningEntries={turnReasoningLog}
            decision={enrichedDecision}
            status={currentStatus}
            customer={selectedCustomer}
            order={currentOrder}
            sessionLog={sessionLog}
          />
        </div>
      </div>
    </>
  );
}
