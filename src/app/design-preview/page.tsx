"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bell,
  BookOpen,
  BrainCircuit,
  ChartCandlestick,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Compass,
  Eye,
  FileText,
  Gauge,
  Layers,
  LayoutDashboard,
  Menu,
  MoreHorizontal,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Sun,
  Moon,
  Wallet,
  X,
} from "lucide-react";
import styles from "@/components/layout/Workspace.module.css";

type Screen =
  | "Overview"
  | "Index terminal"
  | "Option chain"
  | "Paper trading"
  | "Performance"
  | "AI insights"
  | "Sentiment"
  | "Outlook"
  | "Patterns"
  | "Research"
  | "Alerts"
  | "Observer"
  | "Stock explorer"
  | "Stock analysis";
const sections = [
  {
    title: "WORKSPACE",
    items: [
      { title: "Overview" as Screen, icon: LayoutDashboard },
      { title: "Index terminal" as Screen, icon: ChartCandlestick },
      { title: "Option chain" as Screen, icon: Layers },
      { title: "Stock explorer" as Screen, icon: Search },
      { title: "Paper trading" as Screen, icon: Wallet },
      { title: "Performance" as Screen, icon: Activity },
    ],
  },
  {
    title: "INTELLIGENCE",
    items: [
      { title: "AI insights" as Screen, icon: BrainCircuit },
      { title: "Sentiment" as Screen, icon: Gauge },
      { title: "Outlook" as Screen, icon: Compass },
      { title: "Patterns" as Screen, icon: ChartCandlestick },
      { title: "Research" as Screen, icon: BookOpen },
    ],
  },
  {
    title: "MONITOR",
    items: [
      { title: "Alerts" as Screen, icon: Bell },
      { title: "Observer" as Screen, icon: Eye },
    ],
  },
];
const indices = [
  {
    name: "NIFTY 50",
    price: "25,187.40",
    change: "+124.65",
    pct: "+0.50%",
    points: [35, 31, 42, 37, 48, 40, 51, 46, 54, 49, 63, 59, 73, 69, 81],
    positive: true,
  },
  {
    name: "BANK NIFTY",
    price: "61,306.70",
    change: "+286.20",
    pct: "+0.47%",
    points: [30, 42, 33, 51, 42, 58, 47, 61, 54, 66, 59, 71, 64, 80, 76],
    positive: true,
  },
  {
    name: "FINNIFTY",
    price: "27,907.80",
    change: "−48.30",
    pct: "−0.17%",
    points: [78, 74, 80, 65, 69, 57, 63, 49, 55, 41, 49, 34, 40, 26, 30],
    positive: false,
  },
  {
    name: "INDIA VIX",
    price: "15.78",
    change: "−0.64",
    pct: "−3.90%",
    points: [80, 72, 75, 65, 60, 63, 49, 52, 39, 44, 30, 34, 26, 30, 21],
    positive: false,
  },
];
const subtitles: Record<Screen, string> = {
  "Stock explorer":
    "Discover Indian equities in a focused, searchable watchlist.",
  "Stock analysis":
    "Company context, price action and evidence for your research.",
  Overview: "A clearer view of the market. A more deliberate next move.",
  "Index terminal":
    "Price action, structure and evidence in one focused workspace.",
  "Option chain":
    "Understand positioning across strikes before choosing a contract.",
  "Paper trading": "Practice your edge. Protect your process. No real capital.",
  Performance: "Measure the process behind every outcome.",
  "AI insights":
    "Evidence first. Explanations second. Every insight traceable.",
  Sentiment: "The forces shaping market conviction, at a glance.",
  Outlook:
    "Prepare for the session with clear scenarios and invalidation levels.",
  Patterns:
    "Market structure worth watching, with confirmation still required.",
  Research: "Turn your trading library into a searchable knowledge workspace.",
  Alerts: "Less noise. More attention on the levels that matter.",
  Observer:
    "Follow the decision pipeline from incoming data to market assessment.",
};

function Tag({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return (
    <span className={`${styles.tag} ${styles[tone] || ""}`}>{children}</span>
  );
}
function Panel({
  title,
  eyebrow,
  action,
  children,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`${styles.panel} ${className}`}>
      <div className={styles.panelHeading}>
        <div>
          {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
function Sparkline({
  points,
  positive = true,
}: {
  points: number[];
  positive?: boolean;
}) {
  const coords = points.map((p, i) => `${i * 9},${95 - p}`).join(" ");
  return (
    <svg viewBox="0 0 126 80" className={styles.sparkline} aria-hidden="true">
      <polyline
        points={coords}
        fill="none"
        stroke={positive ? "#38c8a5" : "#ed8292"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function PriceChart({
  timeframe,
  instrument,
}: {
  timeframe: string;
  instrument: string;
}) {
  const quote = indices.find((item) => item.name === instrument) || indices[0];
  const axisTop = Math.ceil(Number(quote.price.replaceAll(",", "")) / 50) * 50 + 100;
  const shift =
    timeframe === "1m"
      ? 4
      : timeframe === "15m"
        ? 12
        : timeframe === "1H"
          ? 20
          : 0;
  const candles = Array.from({ length: 64 }, (_, i) => {
    const base =
      230 - i * 1.7 + Math.sin((i + shift) / 3) * 28 + Math.cos(i * 1.9) * 10;
    const up = (i + shift) % 5 !== 0 && i % 7 !== 0;
    return { x: 38 + i * 10.8, y: base, up, h: 5 + ((i * 7) % 14) };
  });
  return (
    <div
      className={styles.chart}
      role="img"
      aria-label={`Illustrative ${instrument} candlestick chart, ${timeframe}. Sample data, not a live market feed.`}
    >
      <svg viewBox="0 0 800 340" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="chart-area" x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#36c4a3" stopOpacity=".09" />
            <stop offset="1" stopColor="#36c4a3" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[45, 100, 155, 210, 265].map((y, i) => (
          <g key={y}>
            <line
              x1="20"
              x2="730"
              y1={y}
              y2={y}
              stroke="currentColor"
              opacity=".07"
            />
            <text
              x="742"
              y={y + 4}
              fill="currentColor"
              opacity=".5"
              fontSize="10"
            >
              {(axisTop - i * 50).toLocaleString("en-IN")}
            </text>
          </g>
        ))}
        {[50, 180, 310, 440, 570, 700].map((x, i) => (
          <g key={x}>
            <line
              x1={x}
              x2={x}
              y1="20"
              y2="280"
              stroke="currentColor"
              opacity=".04"
            />
            <text
              x={x - 12}
              y="327"
              fill="currentColor"
              opacity=".45"
              fontSize="10"
            >
              {["09:15", "10:00", "10:45", "11:30", "12:15", "13:00"][i]}
            </text>
          </g>
        ))}
        <rect
          x="20"
          y="139"
          width="710"
          height="29"
          fill="#38c8a5"
          opacity=".035"
        />
        <line
          x1="20"
          x2="730"
          y1="139"
          y2="139"
          stroke="#38c8a5"
          opacity=".3"
          strokeDasharray="5 5"
        />
        <text x="29" y="132" fill="#38c8a5" fontSize="9" letterSpacing="1">
          DEMAND ZONE
        </text>
        <path
          d={`M${candles.map((c) => `${c.x},${c.y + 30}`).join(" L")}`}
          fill="none"
          stroke="#e3b86d"
          strokeWidth="1.5"
          opacity=".7"
        />
        {candles.map((c, i) => (
          <g
            key={i}
            fill={c.up ? "#38c8a5" : "#ed8292"}
            stroke={c.up ? "#38c8a5" : "#ed8292"}
          >
            <line x1={c.x} x2={c.x} y1={c.y - 9} y2={c.y + c.h + 8} />
            <rect x={c.x - 2.8} y={c.y} width="5.6" height={c.h} rx=".7" />
            <rect
              x={c.x - 3}
              y={307 - ((i * 13) % 26)}
              width="6"
              height={8 + ((i * 13) % 26)}
              stroke="none"
              opacity=".18"
            />
          </g>
        ))}
        <line
          x1="20"
          x2="730"
          y1={candles[63].y}
          y2={candles[63].y}
          stroke="#38c8a5"
          opacity=".65"
          strokeDasharray="3 4"
        />
        <rect
          x="731"
          y={candles[63].y - 9}
          width="66"
          height="20"
          rx="3"
          fill="#38c8a5"
        />
        <text
          x="735"
          y={candles[63].y + 4}
          fill="#062c24"
          fontSize="10"
          fontWeight="700"
        >
          {quote.price}
        </text>
      </svg>
    </div>
  );
}

export default function DesignPreviewPage() {
  const [screen, setScreen] = useState<Screen>("Overview");
  const [instrument, setInstrument] = useState("NIFTY 50");
  const [timeframe, setTimeframe] = useState("5m");
  const [light, setLight] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [tradeTab, setTradeTab] = useState("Open positions");
  const [enabledAlerts, setEnabledAlerts] = useState([true, true, false]);
  const [researchQuery, setResearchQuery] = useState("");
  const [stockQuery, setStockQuery] = useState("");
  const [selectedStock, setSelectedStock] = useState("RELIANCE");
  const stocks = [
    {
      symbol: "RELIANCE",
      name: "Reliance Industries",
      sector: "Energy",
      price: "1,456.80",
      change: "+1.24%",
    },
    {
      symbol: "TCS",
      name: "Tata Consultancy Services",
      sector: "Technology",
      price: "3,480.00",
      change: "+0.82%",
    },
    {
      symbol: "HDFCBANK",
      name: "HDFC Bank",
      sector: "Banking",
      price: "1,720.00",
      change: "+0.35%",
    },
    {
      symbol: "INFY",
      name: "Infosys",
      sector: "Technology",
      price: "1,480.00",
      change: "−0.45%",
    },
    {
      symbol: "ICICIBANK",
      name: "ICICI Bank",
      sector: "Banking",
      price: "1,245.50",
      change: "+0.95%",
    },
  ];
  const navigate = (next: Screen) => {
    setScreen(next);
    setMobileOpen(false);
    setQuery("");
    setNotice("");
  };
  const selectedQuote =
    indices.find((i) => i.name === instrument) || indices[0];
  const actions = (
    <button
      className={styles.iconButton}
      aria-label="About this panel"
      onClick={() =>
        setNotice(
          "This is a design preview. All figures and chart shapes are illustrative sample data.",
        )
      }
    >
      <MoreHorizontal size={18} />
    </button>
  );
  const chartPanel = (
    <Panel
      title={instrument}
      eyebrow="PRICE ACTION"
      action={
        <div className={styles.segmented}>
          {["1m", "5m", "15m", "1H"].map((t) => (
            <button
              key={t}
              aria-pressed={timeframe === t}
              className={timeframe === t ? styles.selected : ""}
              onClick={() => setTimeframe(t)}
            >
              {t}
            </button>
          ))}
        </div>
      }
    >
      <div className={styles.chartQuote}>
        <strong>{selectedQuote.price}</strong>
        <span
          className={
            selectedQuote.positive ? styles.positiveText : styles.negativeText
          }
        >
          {selectedQuote.change} ({selectedQuote.pct})
        </span>
        <span className={styles.muted}>NSE · Sample session</span>
      </div>
      <div className={styles.chartLegend}>
        <span>
          <i style={{ background: "#38c8a5" }} /> Candlesticks
        </span>
        <span>
          <i style={{ background: "#e3b86d" }} /> EMA 20
        </span>
        <span className={styles.muted}>
          O 25,065.20 &nbsp; H 25,210.00 &nbsp; L 25,041.10
        </span>
      </div>
      <PriceChart timeframe={timeframe} instrument={instrument} />
      <div className={styles.chartFooter}>
        <span>
          <span className={styles.dot} /> Illustrative chart
        </span>
        <span>Asia/Kolkata (UTC +5:30)</span>
        <button onClick={() => navigate("Index terminal")}>
          Open terminal <ArrowUpRight size={13} />
        </button>
      </div>
    </Panel>
  );
  const watchlist = (
    <Panel title="Market watch" action={actions}>
      <div className={styles.watchHead}>
        <span>INSTRUMENT</span>
        <span>LAST / CHANGE</span>
      </div>
      {indices.map((i) => (
        <button
          key={i.name}
          className={styles.watchRow}
          onClick={() => {
            setInstrument(i.name === "INDIA VIX" ? "NIFTY 50" : i.name);
            navigate(i.name === "INDIA VIX" ? "Sentiment" : "Index terminal");
          }}
        >
          <span className={styles.watchName}>
            <span className={styles.instrumentIcon}>{i.name.slice(0, 1)}</span>
            <span>
              <b>{i.name}</b>
              <small>
                {i.name === "INDIA VIX" ? "Volatility index" : "NSE index"}
              </small>
            </span>
          </span>
          <span>
            <b>{i.price}</b>
            <small
              className={i.positive ? styles.positiveText : styles.negativeText}
            >
              {i.pct}
            </small>
          </span>
        </button>
      ))}
      <button
        className={styles.textButton}
        onClick={() => navigate("Option chain")}
      >
        Explore option chain <ArrowRight size={14} />
      </button>
    </Panel>
  );
  const signalCards = (
    <div className={styles.signalGrid}>
      {[
        {
          title: "NIFTY 50",
          type: "Bullish watch",
          tone: "positive",
          setup: "Liquidity sweep + FVG retest",
          level: "25,210.00",
          note: "Awaiting candle close",
          icon: ArrowUpRight,
        },
        {
          title: "BANK NIFTY",
          type: "Neutral",
          tone: "warning",
          setup: "Range-bound accumulation",
          level: "61,450.00",
          note: "No confirmed displacement",
          icon: ArrowRight,
        },
        {
          title: "FINNIFTY",
          type: "Bearish watch",
          tone: "negative",
          setup: "Supply zone rejection",
          level: "27,850.00",
          note: "Awaiting structure break",
          icon: ArrowDownRight,
        },
      ].map((s) => (
        <button
          key={s.title}
          className={styles.setupCard}
          onClick={() => {
            setInstrument(s.title);
            navigate("Index terminal");
          }}
        >
          <div className={styles.row}>
            <b>{s.title}</b>
            <Tag tone={s.tone}>{s.type}</Tag>
          </div>
          <div className={styles.setupIcon}>
            <s.icon size={21} />
          </div>
          <h3>{s.setup}</h3>
          <p>
            Confirmation level <strong>{s.level}</strong>
          </p>
          <div className={styles.setupFooter}>
            <span>
              <span className={styles.dot} />
              {s.note}
            </span>
            <ArrowUpRight size={15} />
          </div>
        </button>
      ))}
    </div>
  );
  const metrics = (
    items: {
      label: string;
      value: string;
      detail: string;
      positive?: boolean;
    }[],
  ) => (
    <div className={styles.metricGrid}>
      {items.map((m) => (
        <section className={styles.metricCard} key={m.label}>
          <span>{m.label}</span>
          <strong>{m.value}</strong>
          <small className={m.positive ? styles.positiveText : styles.muted}>
            {m.detail}
          </small>
        </section>
      ))}
    </div>
  );
  const tradeTable = (
    <div className={styles.tableScroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            {[
              "Contract",
              "Side",
              "Quantity",
              "Entry",
              "Mark",
              "P&L",
              "Status",
            ].map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(tradeTab === "Open positions"
            ? [
                [
                  "NIFTY 25200 CE",
                  "BUY",
                  "50",
                  "₹105.00",
                  "₹118.20",
                  "+₹660.00",
                  "Open",
                ],
                [
                  "BANKNIFTY 61200 CE",
                  "BUY",
                  "15",
                  "₹245.50",
                  "₹238.00",
                  "−₹112.50",
                  "Open",
                ],
              ]
            : [
                [
                  "NIFTY 25100 PE",
                  "BUY",
                  "50",
                  "₹120.00",
                  "₹138.50",
                  "+₹925.00",
                  "Closed",
                ],
                [
                  "FINNIFTY 27900 CE",
                  "BUY",
                  "25",
                  "₹82.00",
                  "₹75.00",
                  "−₹175.00",
                  "Closed",
                ],
              ]
          ).map((r, i) => (
            <tr key={r[0]}>
              {r.map((v, j) => (
                <td
                  key={j}
                  className={
                    j === 5
                      ? i === 0
                        ? styles.positiveText
                        : styles.negativeText
                      : ""
                  }
                >
                  {j === 1 || j === 6 ? (
                    <Tag tone={j === 1 ? "positive" : "neutral"}>{v}</Tag>
                  ) : (
                    v
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  function renderScreen() {
    switch (screen) {
      case "Overview":
        return (
          <>
            <div className={styles.indexGrid}>
              {indices.map((i) => (
                <button
                  key={i.name}
                  className={`${styles.indexCard} ${instrument === i.name ? styles.indexActive : ""}`}
                  onClick={() => {
                    if (i.name === "INDIA VIX") navigate("Sentiment");
                    else setInstrument(i.name);
                  }}
                >
                  <div className={styles.row}>
                    <span>{i.name}</span>
                    {i.positive ? (
                      <ArrowUpRight size={15} />
                    ) : (
                      <ArrowDownRight size={15} />
                    )}
                  </div>
                  <strong>{i.price}</strong>
                  <div className={styles.row}>
                    <span
                      className={
                        i.positive ? styles.positiveText : styles.negativeText
                      }
                    >
                      {i.change} <small>({i.pct})</small>
                    </span>
                    <span className={styles.muted}>NSE</span>
                  </div>
                  <Sparkline points={i.points} positive={i.positive} />
                </button>
              ))}
            </div>
            <div className={styles.mainGrid}>
              {chartPanel}
              <div className={styles.stack}>
                <Panel
                  title="Your market copilot"
                  eyebrow="AIVOLVE INTELLIGENCE"
                  className={styles.insightPanel}
                  action={<Sparkles size={18} />}
                >
                  <div className={styles.insightOrb}>
                    <BrainCircuit size={29} />
                  </div>
                  <h3>Patience is a position.</h3>
                  <p>
                    The sample market is testing a key supply zone. Watch for a
                    confirmed close before committing to direction.
                  </p>
                  <div className={styles.insightFact}>
                    <ShieldCheck size={16} />
                    <span>
                      Wait for confirmation<small>Evidence over impulse</small>
                    </span>
                  </div>
                  <button
                    className={styles.primaryButton}
                    onClick={() => navigate("AI insights")}
                  >
                    Explore the analysis <ArrowUpRight size={15} />
                  </button>
                </Panel>
                {watchlist}
              </div>
            </div>
            <div className={styles.sectionTitle}>
              <div>
                <h2>Setups on your radar</h2>
                <p>A watchlist of possibilities. Confirmation comes first.</p>
              </div>
              <button
                className={styles.textButton}
                onClick={() => navigate("Patterns")}
              >
                All setups <ArrowRight size={15} />
              </button>
            </div>
            {signalCards}
            <div className={styles.bottomGrid}>
              <Panel title="Session pulse" action={<Tag>Sample</Tag>}>
                <div className={styles.pulseGrid}>
                  <div>
                    <span>Market breadth</span>
                    <strong>Balanced</strong>
                    <div className={styles.breadth}>
                      <i />
                      <i />
                    </div>
                    <small>28 advancing · 22 declining</small>
                  </div>
                  <div>
                    <span>Volatility</span>
                    <strong>
                      15.78 <small className={styles.positiveText}>Low</small>
                    </strong>
                    <p>Conditions favor selective entries.</p>
                  </div>
                  <div>
                    <span>Next event</span>
                    <strong>Macro briefing</strong>
                    <p>Illustrative event · 16:00 IST</p>
                  </div>
                </div>
              </Panel>
              <Panel title="Your paper account" action={<Wallet size={18} />}>
                <div className={styles.accountBalance}>
                  ₹1,00,000<span>Virtual starting balance</span>
                </div>
                <button
                  className={styles.textButton}
                  onClick={() => navigate("Paper trading")}
                >
                  Open paper workspace <ArrowRight size={14} />
                </button>
              </Panel>
            </div>
          </>
        );
      case "Index terminal":
        return (
          <>
            <div className={styles.toolbar}>
              <div className={styles.segmented}>
                {["NIFTY 50", "BANK NIFTY", "FINNIFTY"].map((i) => (
                  <button
                    key={i}
                    className={instrument === i ? styles.selected : ""}
                    onClick={() => setInstrument(i)}
                  >
                    {i}
                  </button>
                ))}
              </div>
              <Tag tone="warning">Awaiting confirmation</Tag>
            </div>
            <div className={styles.mainGrid}>
              {chartPanel}
              <div className={styles.stack}>
                <Panel title="Trade thesis" eyebrow="STRUCTURE & CONTEXT">
                  <Tag tone="positive">Bullish watch</Tag>
                  <h3 className={styles.thesis}>
                    Demand held. Confirmation pending.
                  </h3>
                  <p className={styles.copy}>
                    Watch the prior swing high. A close above supply with
                    displacement supports the bullish scenario.
                  </p>
                  {[
                    ["Market structure", "Higher low"],
                    ["15m / 5m alignment", "Mixed"],
                    ["Liquidity sweep", "Detected"],
                    ["Execution", "Wait"],
                  ].map(([l, v]) => (
                    <div className={styles.detailRow} key={l}>
                      <span>{l}</span>
                      <b>{v}</b>
                    </div>
                  ))}
                  <button
                    className={styles.primaryButton}
                    onClick={() => navigate("Paper trading")}
                  >
                    Paper trading workspace <ArrowUpRight size={15} />
                  </button>
                </Panel>
                <Panel title="Key levels">
                  {[
                    ["Resistance", "25,310.00"],
                    ["Confirmation", "25,210.00"],
                    ["Support", "25,150.00"],
                    ["Invalidation", "25,100.00"],
                  ].map(([l, v]) => (
                    <div key={l} className={styles.detailRow}>
                      <span>{l}</span>
                      <b>{v}</b>
                    </div>
                  ))}
                </Panel>
              </div>
            </div>
            {signalCards}
          </>
        );
      case "Option chain":
        return (
          <>
            <div className={styles.toolbar}>
              <select
                aria-label="Underlying index"
                value={instrument === "INDIA VIX" ? "NIFTY 50" : instrument}
                onChange={(e) => setInstrument(e.target.value)}
              >
                {["NIFTY 50", "BANK NIFTY", "FINNIFTY"].map((i) => (
                  <option key={i}>{i}</option>
                ))}
              </select>
              <Tag>Illustrative expiry · 26 Nov 2026</Tag>
              <span className={styles.muted}>Spot {selectedQuote.price}</span>
            </div>
            {metrics([
              {
                label: "Put / call ratio",
                value: "1.12",
                detail: "Sample open-interest ratio",
              },
              {
                label: "ATM implied volatility",
                value: "17.8%",
                detail: "Annualized · illustrative",
              },
              {
                label: "Max pain",
                value: "25,200",
                detail: "Illustrative strike",
              },
              {
                label: "Total open interest",
                value: "2.84 Cr",
                detail: "Sample contracts",
              },
            ])}
            <Panel
              title={`${instrument} option chain`}
              action={<Tag tone="positive">Calls / Puts</Tag>}
            >
              <div className={styles.tableScroll}>
                <table className={`${styles.table} ${styles.chain}`}>
                  <thead>
                    <tr>
                      {[
                        "Call OI",
                        "IV",
                        "Delta",
                        "Call LTP",
                        "Strike",
                        "Put LTP",
                        "Delta",
                        "IV",
                        "Put OI",
                      ].map((h, i) => (
                        <th key={i}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: 11 }, (_, i) => (
                      <tr key={i} className={i === 5 ? styles.atmRow : ""}>
                        <td>{(9.8 + i * 1.4).toFixed(2)} L</td>
                        <td>{(19.4 - i * 0.3).toFixed(1)}%</td>
                        <td>{(0.79 - i * 0.05).toFixed(2)}</td>
                        <td className={styles.positiveText}>
                          {(328 - i * 28.4).toFixed(2)}
                        </td>
                        <td className={styles.strike}>
                          {(24950 + i * 50).toLocaleString("en-IN")}
                          {i === 5 && <small>ATM</small>}
                        </td>
                        <td className={styles.negativeText}>
                          {(42 + i * 18.6).toFixed(2)}
                        </td>
                        <td>{(-0.21 - i * 0.05).toFixed(2)}</td>
                        <td>{(16.4 + i * 0.3).toFixed(1)}%</td>
                        <td>{(24.5 - i * 1.4).toFixed(2)} L</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </>
        );
      case "Paper trading":
        return (
          <>
            <div className={styles.infoBanner}>
              <ShieldCheck size={19} />
              <div>
                <b>Your practice arena. Zero real capital.</b>
                <span>
                  Sample positions below demonstrate the interface. No orders
                  are placed in this preview.
                </span>
              </div>
              <Tag tone="positive">Paper only</Tag>
            </div>
            {metrics([
              {
                label: "Virtual account value",
                value: "₹1,00,547.50",
                detail: "Illustrative portfolio",
              },
              {
                label: "Available cash",
                value: "₹91,067.50",
                detail: "After simulated allocation",
              },
              {
                label: "Unrealized P&L",
                value: "+₹547.50",
                detail: "2 sample open positions",
                positive: true,
              },
              {
                label: "Risk status",
                value: "Not connected",
                detail: "Live policy is not loaded",
              },
            ])}
            <Panel
              title="Positions & journal"
              action={
                <div className={styles.segmented}>
                  {["Open positions", "Trade history"].map((t) => (
                    <button
                      key={t}
                      className={tradeTab === t ? styles.selected : ""}
                      onClick={() => setTradeTab(t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              }
            >
              {tradeTable}
            </Panel>
            <div className={styles.bottomGrid}>
              <Panel title="Risk guardrails" action={<ShieldCheck size={18} />}>
                <p className={styles.copy}>
                  Your real risk policy will appear here after backend
                  integration. Preview values never authorize trading.
                </p>
                {[
                  ["Daily drawdown budget", "Not loaded"],
                  ["Capital per trade", "Not loaded"],
                  ["Portfolio Greeks", "Not loaded"],
                ].map(([l, v]) => (
                  <div key={l} className={styles.detailRow}>
                    <span>{l}</span>
                    <Tag>{v}</Tag>
                  </div>
                ))}
              </Panel>
              <Panel title="Trading checklist">
                {[
                  "Confirm market structure",
                  "Check spread and liquidity",
                  "Define invalidation before entry",
                  "Respect the daily risk budget",
                ].map((t) => (
                  <div className={styles.checkRow} key={t}>
                    <Check size={15} />
                    {t}
                  </div>
                ))}
              </Panel>
            </div>
          </>
        );
      case "Performance":
        return (
          <>
            {metrics([
              {
                label: "Net sample P&L",
                value: "+₹8,420",
                detail: "After illustrative costs",
                positive: true,
              },
              { label: "Win rate", value: "58.3%", detail: "24 sample trades" },
              {
                label: "Profit factor",
                value: "1.64",
                detail: "Gross wins / gross losses",
              },
              {
                label: "Maximum drawdown",
                value: "3.2%",
                detail: "Sample account equity",
              },
            ])}
            <div className={styles.mainGrid}>
              <Panel
                title="Equity curve"
                eyebrow="SAMPLE PERFORMANCE"
                action={<Tag>Last 30 sessions</Tag>}
              >
                <div className={styles.equityValue}>
                  ₹1,08,420 <span className={styles.positiveText}>+8.42%</span>
                </div>
                <div className={styles.equityChart}>
                  <svg
                    viewBox="0 0 760 260"
                    role="img"
                    aria-label="Illustrative equity curve"
                  >
                    <defs>
                      <linearGradient
                        id="equity-fill"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop stopColor="#38c8a5" stopOpacity=".2" />
                        <stop offset="1" stopColor="#38c8a5" stopOpacity="0" />
                      </linearGradient>
                    </defs>
                    {[50, 100, 150, 200].map((y) => (
                      <line
                        key={y}
                        x1="0"
                        x2="760"
                        y1={y}
                        y2={y}
                        stroke="currentColor"
                        opacity=".06"
                      />
                    ))}
                    <path
                      d="M0 220 L25 210 50 216 80 184 110 192 140 172 170 183 200 155 230 160 260 132 290 145 320 112 350 128 380 100 410 112 440 78 470 86 500 66 530 75 560 45 590 57 620 40 650 48 680 22 720 30 760 15 L760 260 L0 260Z"
                      fill="url(#equity-fill)"
                    />
                    <path
                      d="M0 220 L25 210 50 216 80 184 110 192 140 172 170 183 200 155 230 160 260 132 290 145 320 112 350 128 380 100 410 112 440 78 470 86 500 66 530 75 560 45 590 57 620 40 650 48 680 22 720 30 760 15"
                      fill="none"
                      stroke="#38c8a5"
                      strokeWidth="2.5"
                    />
                  </svg>
                </div>
              </Panel>
              <Panel title="Process quality">
                {[
                  ["Entry discipline", 82],
                  ["Risk adherence", 94],
                  ["Confirmation quality", 76],
                  ["Exit discipline", 68],
                ].map(([l, v]) => (
                  <div className={styles.progressItem} key={l}>
                    <div className={styles.row}>
                      <span>{l}</span>
                      <b>{v}%</b>
                    </div>
                    <div className={styles.progress}>
                      <i style={{ width: `${v}%` }} />
                    </div>
                  </div>
                ))}
                <p className={styles.copy}>
                  Sample metrics demonstrate the layout; they do not establish
                  strategy performance.
                </p>
              </Panel>
            </div>
            <Panel title="Recent sample trades">{tradeTable}</Panel>
          </>
        );
      case "AI insights":
        return (
          <>
            <div className={styles.aiHero}>
              <div className={styles.insightOrb}>
                <Sparkles size={30} />
              </div>
              <Tag tone="positive">Your research copilot</Tag>
              <h2>
                Understand the why.
                <br />
                <span>Before the next move.</span>
              </h2>
              <p>
                Quantitative evidence, market context and your research library,
                brought together in one clear explanation.
              </p>
            </div>
            <div className={styles.signalGrid}>
              {[
                {
                  title: "Market structure",
                  text: "A higher low is forming near demand. The swing high remains the confirmation level.",
                  icon: ChartCandlestick,
                },
                {
                  title: "Volatility context",
                  text: "Compare premium, implied volatility and holding time before evaluating a setup.",
                  icon: Activity,
                },
                {
                  title: "Risk perspective",
                  text: "A setup becomes actionable only when data quality and every risk gate agree.",
                  icon: ShieldCheck,
                },
              ].map((c) => (
                <Panel
                  key={c.title}
                  title={c.title}
                  action={<c.icon size={20} />}
                >
                  <p className={styles.copy}>{c.text}</p>
                  <Tag>Sample explanation</Tag>
                </Panel>
              ))}
            </div>
            <Panel
              title="Ask your trading library"
              action={<BookOpen size={18} />}
            >
              <form
                className={styles.askForm}
                onSubmit={(e) => {
                  e.preventDefault();
                  setNotice(
                    "Design preview: a connected research backend will answer questions with document citations.",
                  );
                }}
              >
                <input
                  aria-label="Research question"
                  required
                  placeholder="What confirms a liquidity sweep before an entry?"
                />
                <button className={styles.primaryButton}>
                  Ask copilot <ArrowRight size={16} />
                </button>
              </form>
              <p className={styles.copy}>
                Research assistance, with source citations. Numerical targets
                come from the quant engine.
              </p>
            </Panel>
          </>
        );
      case "Sentiment":
        return (
          <>
            {metrics([
              {
                label: "Market bias",
                value: "Balanced",
                detail: "Illustrative composite reading",
              },
              {
                label: "Put / call ratio",
                value: "1.12",
                detail: "Sample derivatives positioning",
              },
              {
                label: "Volatility index",
                value: "15.78",
                detail: "Sample India VIX",
              },
              {
                label: "Breadth",
                value: "28 / 22",
                detail: "Advancers / decliners",
              },
            ])}
            <div className={styles.bottomGrid}>
              <Panel title="The conviction spectrum" eyebrow="SAMPLE SENTIMENT">
                <div className={styles.sentimentGauge}>
                  <Gauge size={90} />
                  <strong>
                    54<span>Neutral</span>
                  </strong>
                </div>
                <div className={styles.sentimentScale} />
                <div className={styles.row}>
                  <small>Fear</small>
                  <small>Balanced</small>
                  <small>Greed</small>
                </div>
              </Panel>
              <Panel title="What's shaping the market">
                {[
                  ["Derivatives positioning", "Mildly positive"],
                  ["Index participation", "Mixed"],
                  ["Price / VWAP relationship", "Above VWAP"],
                  ["News catalyst", "Unverified in preview"],
                ].map(([l, v]) => (
                  <div className={styles.detailRow} key={l}>
                    <span>{l}</span>
                    <b>{v}</b>
                  </div>
                ))}
                <p className={styles.copy}>
                  Sample context only. Real news and institutional flows require
                  source verification.
                </p>
              </Panel>
            </div>
            {watchlist}
          </>
        );
      case "Outlook":
        return (
          <>
            <div className={styles.infoBanner}>
              <Compass size={20} />
              <div>
                <b>Plan scenarios. Let price confirm.</b>
                <span>
                  Illustrative levels demonstrate the design; they are not
                  trading recommendations.
                </span>
              </div>
            </div>
            <div className={styles.signalGrid}>
              {[
                {
                  name: "Bullish scenario",
                  tone: "positive",
                  trigger: "Above 25,210",
                  note: "A confirmed close with expanding participation.",
                  invalid: "Below 25,150",
                },
                {
                  name: "Base scenario",
                  tone: "warning",
                  trigger: "25,150 — 25,210",
                  note: "Range persists. Wait for clean displacement.",
                  invalid: "Confirmed range break",
                },
                {
                  name: "Bearish scenario",
                  tone: "negative",
                  trigger: "Below 25,150",
                  note: "Demand fails and a lower high is confirmed.",
                  invalid: "Reclaim of 25,210",
                },
              ].map((s) => (
                <Panel
                  key={s.name}
                  title={s.name}
                  action={<Tag tone={s.tone}>Scenario</Tag>}
                >
                  <h3 className={styles.scenarioLevel}>{s.trigger}</h3>
                  <p className={styles.copy}>{s.note}</p>
                  <div className={styles.detailRow}>
                    <span>Invalidation</span>
                    <b>{s.invalid}</b>
                  </div>
                </Panel>
              ))}
            </div>
            {chartPanel}
          </>
        );
      case "Patterns":
        return (
          <>
            <div className={styles.sectionTitle}>
              <div>
                <h2>Structure, not speculation</h2>
                <p>
                  Every pattern needs confirmation and a clear invalidation.
                </p>
              </div>
              <Tag>3 sample setups</Tag>
            </div>
            {signalCards}
            <div className={styles.bottomGrid}>
              <Panel title="Multi-timeframe alignment">
                {[
                  ["1 hour", "Neutral"],
                  ["15 minute", "Bullish watch"],
                  ["5 minute", "Awaiting displacement"],
                  ["1 minute", "Execution not armed"],
                ].map(([l, v]) => (
                  <div className={styles.detailRow} key={l}>
                    <span>{l}</span>
                    <Tag tone={l === "15 minute" ? "positive" : "neutral"}>
                      {v}
                    </Tag>
                  </div>
                ))}
              </Panel>
              <Panel title="Confirmation checklist">
                {[
                  "Liquidity taken beyond a prior swing",
                  "Market structure shift on a closed candle",
                  "Fair value gap with clear invalidation",
                  "Risk and liquidity checks satisfied",
                ].map((t) => (
                  <div className={styles.checkRow} key={t}>
                    <Check size={15} />
                    {t}
                  </div>
                ))}
              </Panel>
            </div>
          </>
        );
      case "Research":
        return (
          <>
            <div className={styles.researchHero}>
              <BookOpen size={28} />
              <h2>Your knowledge. Connected.</h2>
              <p>
                A considered home for trading notes, source documents and
                research.
              </p>
              <label className={styles.search}>
                <Search size={17} />
                <input
                  placeholder="Search the sample library..."
                  aria-label="Search research library"
                  value={researchQuery}
                  onChange={(e) => setResearchQuery(e.target.value)}
                />
              </label>
            </div>
            <div className={styles.signalGrid}>
              {[
                "Market structure fundamentals",
                "Risk management playbook",
                "Options & volatility notes",
              ]
                .filter((t) =>
                  t.toLowerCase().includes(researchQuery.toLowerCase()),
                )
                .map((t) => (
                  <Panel key={t} title={t} action={<FileText size={20} />}>
                    <p className={styles.copy}>
                      {
                        [
                          "A framework for swings, structure shifts and liquidity.",
                          "Sizing, drawdown limits and decision discipline.",
                          "Greeks, spread, expiry and premium behavior.",
                        ][["Market structure fundamentals", "Risk management playbook", "Options & volatility notes"].indexOf(t)]
                      }
                    </p>
                    <div className={styles.row}>
                      <Tag>Sample document</Tag>
                      <button
                        className={styles.iconButton}
                        aria-label={`Read ${t}`}
                        onClick={() =>
                          setNotice(
                            `${t}: this sample document card will open a source-backed reader after integration.`,
                          )
                        }
                      >
                        <ArrowUpRight size={17} />
                      </button>
                    </div>
                  </Panel>
                ))}
            </div>
            {![
              "Market structure fundamentals",
              "Risk management playbook",
              "Options & volatility notes",
            ].some((t) =>
              t.toLowerCase().includes(researchQuery.toLowerCase()),
            ) && (
              <div className={styles.emptyState}>
                <Search size={28} />
                <h3>No matching sample documents</h3>
                <p>Try searching for structure, risk or options.</p>
              </div>
            )}
            <button
              className={styles.secondaryButton}
              onClick={() =>
                setNotice(
                  "Document upload belongs to the next integration step. No file is uploaded from this design preview.",
                )
              }
            >
              <Plus size={16} /> Add research document
            </button>
          </>
        );
      case "Alerts":
        return (
          <>
            <div className={styles.toolbar}>
              <Tag>
                {enabledAlerts.filter(Boolean).length} enabled in preview
              </Tag>
              <button
                className={styles.secondaryButton}
                onClick={() =>
                  setNotice(
                    "The alert creation flow will connect to verified market levels after UI review.",
                  )
                }
              >
                <Plus size={15} /> New alert
              </button>
            </div>
            <Panel title="Your watch conditions">
              {[
                {
                  title: "NIFTY above confirmation",
                  detail: "Closed candle above 25,210 · Sample price alert",
                },
                {
                  title: "Daily drawdown watch",
                  detail:
                    "Notify when the configured paper risk budget is approached",
                },
                {
                  title: "BANK NIFTY structure break",
                  detail: "Closed candle below demand · Sample structure alert",
                },
              ].map((a, i) => (
                <div key={a.title} className={styles.alertRow}>
                  <span className={styles.alertIcon}>
                    <Bell size={19} />
                  </span>
                  <div>
                    <h3>{a.title}</h3>
                    <p>{a.detail}</p>
                  </div>
                  <button
                    role="switch"
                    aria-checked={enabledAlerts[i]}
                    aria-label={a.title}
                    className={`${styles.toggle} ${enabledAlerts[i] ? styles.toggleOn : ""}`}
                    onClick={() =>
                      setEnabledAlerts((p) =>
                        p.map((v, j) => (j === i ? !v : v)),
                      )
                    }
                  >
                    <span />
                  </button>
                </div>
              ))}
            </Panel>
            <p className={styles.copy}>
              Preview switches only change this screen. They do not create
              notifications or trading automations.
            </p>
          </>
        );
      case "Stock explorer":
        return (
          <>
            <label className={styles.search}>
              <Search size={17} />
              <input
                placeholder="Search sample Indian equities..."
                aria-label="Search sample equities"
                value={stockQuery}
                onChange={(e) => setStockQuery(e.target.value)}
              />
            </label>
            <Panel
              title="Equity watchlist"
              action={<Tag>NSE · Sample quotes</Tag>}
            >
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      {[
                        "Company",
                        "Sector",
                        "Sample price",
                        "Change",
                        "Research",
                      ].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {stocks
                      .filter((s) =>
                        `${s.name} ${s.symbol} ${s.sector}`
                          .toLowerCase()
                          .includes(stockQuery.toLowerCase()),
                      )
                      .map((s) => (
                        <tr key={s.symbol}>
                          <td>
                            <b>{s.symbol}</b>
                            <div className={styles.muted}>{s.name}</div>
                          </td>
                          <td>{s.sector}</td>
                          <td>₹{s.price}</td>
                          <td
                            className={
                              s.change.startsWith("+")
                                ? styles.positiveText
                                : styles.negativeText
                            }
                          >
                            {s.change}
                          </td>
                          <td>
                            <button
                              className={styles.secondaryButton}
                              onClick={() => {
                                setSelectedStock(s.symbol);
                                navigate("Stock analysis");
                              }}
                            >
                              Analyze <ArrowUpRight size={13} />
                            </button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              {!stocks.some((s) =>
                `${s.name} ${s.symbol} ${s.sector}`
                  .toLowerCase()
                  .includes(stockQuery.toLowerCase()),
              ) && (
                <div className={styles.emptyState}>
                  <Search size={25} />
                  <h3>No matching sample equities</h3>
                  <p>Try a company name, symbol or sector.</p>
                </div>
              )}
            </Panel>
          </>
        );
      case "Stock analysis": {
        const stock =
          stocks.find((s) => s.symbol === selectedStock) || stocks[0];
        return (
          <>
            <div className={styles.toolbar}>
              <button
                className={styles.secondaryButton}
                onClick={() => navigate("Stock explorer")}
              >
                ← All equities
              </button>
              <Tag>NSE · Sample company view</Tag>
            </div>
            <Panel
              title={stock.name}
              eyebrow={stock.symbol}
              action={<Tag>{stock.sector}</Tag>}
            >
              <div className={styles.equityValue}>
                ₹{stock.price}{" "}
                <span
                  className={
                    stock.change.startsWith("+")
                      ? styles.positiveText
                      : styles.negativeText
                  }
                >
                  {stock.change}
                </span>
              </div>
              <p className={styles.copy}>
                Illustrative quote for interface review. A verified feed will
                supply the actual market price and timestamp.
              </p>
            </Panel>
            <div className={styles.bottomGrid}>
              <Panel title="Technical perspective">
                {[
                  ["Trend context", "Awaiting verified candles"],
                  ["Support & resistance", "Quant engine required"],
                  ["Momentum", "Not evaluated in preview"],
                  ["Qualified setup", "No trade recommendation"],
                ].map(([l, v]) => (
                  <div key={l} className={styles.detailRow}>
                    <span>{l}</span>
                    <b>{v}</b>
                  </div>
                ))}
              </Panel>
              <Panel title="Research notes" action={<BookOpen size={18} />}>
                <p className={styles.copy}>
                  Bring price action together with company filings, sector
                  context and attributable news before forming a view.
                </p>
                <button
                  className={styles.textButton}
                  onClick={() => navigate("Research")}
                >
                  Open research library <ArrowRight size={14} />
                </button>
              </Panel>
            </div>
          </>
        );
      }
      case "Observer":
        return (
          <>
            {metrics([
              {
                label: "Feed connection",
                value: "Preview",
                detail: "No live data subscription",
              },
              {
                label: "Eligible samples",
                value: "—",
                detail: "Requires verified session data",
              },
              {
                label: "Matured outcomes",
                value: "—",
                detail: "Requires forward observation",
              },
              {
                label: "Execution mode",
                value: "Paper only",
                detail: "No real broker routing",
              },
            ])}
            <Panel
              title="Decision pipeline"
              action={<Tag>Illustrative sequence</Tag>}
            >
              <div className={styles.pipeline}>
                {[
                  {
                    title: "Market data received",
                    text: "Validate source, exchange timestamp and quote freshness.",
                  },
                  {
                    title: "Features computed",
                    text: "Closed-candle indicators and multi-timeframe evidence.",
                  },
                  {
                    title: "Structure assessed",
                    text: "Market regime, liquidity and confirmation conditions.",
                  },
                  {
                    title: "Risk gates evaluated",
                    text: "Budget, portfolio exposure and contract liquidity.",
                  },
                  {
                    title: "Decision recorded",
                    text: "Wait, no trade or qualified setup, with an auditable reason.",
                  },
                ].map((e, i) => (
                  <div className={styles.pipelineItem} key={e.title}>
                    <span>{String(i + 1).padStart(2, "0")}</span>
                    <div>
                      <h3>{e.title}</h3>
                      <p>{e.text}</p>
                    </div>
                    <Check size={16} />
                  </div>
                ))}
              </div>
            </Panel>
          </>
        );
    }
  }

  return (
    <div className={`${styles.workspace} ${light ? styles.light : ""}`}>
      {mobileOpen && (
        <button
          className={styles.backdrop}
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={`${styles.sidebar} ${mobileOpen ? styles.sidebarOpen : ""}`}
      >
        <button className={styles.brand} onClick={() => navigate("Overview")}>
          <span className={styles.brandIcon}>
            <Activity size={23} />
          </span>
          <span>
            AIVOLVE
            <span className={styles.brandSuffix}>TRADING INTELLIGENCE</span>
          </span>
          <span className={styles.brandVersion}>/ 03</span>
        </button>
        <div className={styles.workspacePicker}>
          <span className={styles.workspaceAvatar}>A</span>
          <span>
            <b>Personal workspace</b>
            <small>Paper trading environment</small>
          </span>
          <ChevronDown size={14} />
        </div>
        <nav aria-label="Preview navigation">
          {sections.map((s) => (
            <div key={s.title} className={styles.navGroup}>
              <p>{s.title}</p>
              {s.items.map((i) => (
                <button
                  key={i.title}
                  aria-current={screen === i.title ? "page" : undefined}
                  className={`${styles.navItem} ${screen === i.title ? styles.navActive : ""}`}
                  onClick={() => navigate(i.title)}
                >
                  <i.icon size={17} />
                  <span>{i.title}</span>
                  {i.title === "AI insights" && (
                    <span className={styles.aiLabel}>AI</span>
                  )}
                  {i.title === "Alerts" && <small>3</small>}
                  {screen === i.title && <span className={styles.activeDot} />}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className={styles.sidebarBottom}>
          <div className={styles.safeCard}>
            <ShieldCheck size={18} />
            <b>Built around discipline.</b>
            <p>
              Every good trade starts
              <br />
              with a clear risk boundary.
            </p>
            <button onClick={() => navigate("Paper trading")}>
              Your paper workspace <ArrowUpRight size={13} />
            </button>
          </div>
          <button
            className={styles.helpLink}
            onClick={() =>
              setNotice(
                "Use the sidebar to explore 14 redesigned screens. All values are sample data; the preview does not trade.",
              )
            }
          >
            <CircleHelp size={16} /> Help & design notes{" "}
            <ArrowUpRight size={13} />
          </button>
          <div className={styles.profile}>
            <span className={styles.profileAvatar}>AV</span>
            <span>
              <b>Aivolve Trader</b>
              <small>Personal account</small>
            </span>
            <button
              className={styles.iconButton}
              aria-label="Toggle preview theme"
              onClick={() => setLight(!light)}
            >
              {light ? <Moon size={16} /> : <Sun size={16} />}
            </button>
          </div>
        </div>
      </aside>
      <div className={styles.main}>
        <header className={styles.header}>
          <div className={styles.breadcrumb}>
            <button
              className={`${styles.iconButton} ${styles.mobileMenu}`}
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <b>{screen}</b>
          </div>
          <div className={styles.headerActions}>
            <div className={styles.headerSearch}>
              <Search size={15} />
              <input
                aria-label="Find a preview screen"
                placeholder="Search workspace..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              {query && (
                <div className={styles.searchResults}>
                  {sections
                    .flatMap((s) => s.items)
                    .filter((i) =>
                      i.title.toLowerCase().includes(query.toLowerCase()),
                    )
                    .map((i) => (
                      <button key={i.title} onClick={() => navigate(i.title)}>
                        <i.icon size={15} />
                        {i.title}
                        <ArrowUpRight size={13} />
                      </button>
                    ))}
                  {!sections
                    .flatMap((s) => s.items)
                    .some((i) =>
                      i.title.toLowerCase().includes(query.toLowerCase()),
                    ) && <p>No matching screens</p>}
                </div>
              )}
            </div>
            <span className={styles.headerDivider} />
            <button
              className={styles.iconButton}
              aria-label="Open alerts"
              onClick={() => navigate("Alerts")}
            >
              <Bell size={18} />
              <span className={styles.notificationDot} />
            </button>
            <span className={styles.profileAvatar}>AV</span>
          </div>
        </header>
        <div className={styles.previewStrip}>
          <span>
            <span className={styles.dot} /> DESIGN PREVIEW <b>·</b> Sample data
            throughout
          </span>
          <Link href="/">
            Open current app <ArrowUpRight size={12} />
          </Link>
        </div>
        <main className={styles.content}>
          <div className={styles.pageHeading}>
            <div>
              <div className={styles.eyebrow}>
                YOUR EDGE STARTS WITH CLARITY
              </div>
              <h1>{screen === "Overview" ? "Market overview" : screen}</h1>
              <p>{subtitles[screen]}</p>
            </div>
            <div className={styles.pageActions}>
              <Tag>
                <ShieldCheck size={12} /> Paper mode
              </Tag>
              <button
                className={styles.secondaryButton}
                onClick={() =>
                  setNotice(
                    "Preview session: 16 November 2026. All market values are illustrative, not historical or live quotes.",
                  )
                }
              >
                <span className={styles.calendarIcon}>16</span> Nov 16, 2026{" "}
                <ChevronDown size={13} />
              </button>
            </div>
          </div>
          {notice && (
            <div className={styles.notice} role="status">
              <CircleHelp size={18} />
              <span>{notice}</span>
              <button
                className={styles.iconButton}
                aria-label="Dismiss message"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          <div className={styles.screenContent} key={screen}>
            {renderScreen()}
          </div>
          <footer className={styles.footer}>
            <span>
              <ShieldCheck size={12} /> Designed for thoughtful decisions.
            </span>
            <span>
              Illustrative interface · No investment advice · No real orders
            </span>
            <span>
              AIVOLVE TECH <span className={styles.muted}>© 2026</span>
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
