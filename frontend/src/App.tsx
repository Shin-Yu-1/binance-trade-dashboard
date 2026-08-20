import { useEffect, useMemo, useState } from "react";

import { CandleChart } from "./components/CandleChart";
import { HealthPanel } from "./components/HealthPanel";
import { StatCards } from "./components/StatCards";
import { useLiveFeed } from "./hooks/useLiveFeed";
import { type HealthStatus, fetchCandles, fetchConfig, fetchHealth, fetchStats } from "./lib/api";
import { formatAge } from "./lib/format";
import { deriveStats, parseCandle } from "./lib/liveState";

const FALLBACK_SYMBOLS = ["BTCUSDT", "ETHUSDT"];
const HEALTH_POLL_MS = 3_000;
const CLOCK_TICK_MS = 1_000;

export function App() {
  const [symbols, setSymbols] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchConfig()
      .then((config) => {
        if (!cancelled) setSymbols(config.symbols.length ? config.symbols : FALLBACK_SYMBOLS);
      })
      // 설정 조회가 실패해도 대시보드를 띄운다 — 기본 심볼로 계속 진행.
      .catch(() => {
        if (!cancelled) setSymbols(FALLBACK_SYMBOLS);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!symbols) {
    return <main className="app loading">대시보드를 불러오는 중…</main>;
  }

  return <Dashboard key={symbols.join(",")} symbols={symbols} />;
}

function Dashboard({ symbols }: { symbols: string[] }) {
  const { state, dispatch } = useLiveFeed(symbols);
  const [active, setActive] = useState(symbols[0]);
  const [health, setHealth] = useState<HealthStatus[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [warning, setWarning] = useState<string | null>(null);

  // 초기 이력: 캔들 차트용 1분봉과 24h 테이커 집계를 REST로 한 번 심는다.
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      symbols.map(async (symbol) => {
        const [candles, stats] = await Promise.all([fetchCandles(symbol), fetchStats(symbol)]);
        if (cancelled) return;
        dispatch({ type: "candles", symbol, candles: candles.map(parseCandle) });
        dispatch({ type: "stats", symbol, stats });
      }),
    ).catch(() => {
      if (!cancelled) setWarning("초기 데이터를 불러오지 못했습니다. 실시간 스트림만 표시합니다.");
    });
    return () => {
      cancelled = true;
    };
  }, [symbols, dispatch]);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetchHealth()
        .then((rows) => {
          if (cancelled) return;
          setHealth(rows);
          setWarning(null);
        })
        // 헬스 조회 실패 시에도 마지막 상태를 그대로 두고 경고만 띄운다.
        .catch(() => {
          if (!cancelled) setWarning("서버 상태 조회에 실패했습니다. 표시된 값은 최신이 아닐 수 있습니다.");
        });
    };
    poll();
    const timer = setInterval(poll, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  const symbolState = state.symbols[active];
  const stats = useMemo(() => deriveStats(symbolState?.candles ?? []), [symbolState?.candles]);
  const lastTradeAge =
    symbolState?.lastTradeAt === null || symbolState?.lastTradeAt === undefined
      ? null
      : (now - symbolState.lastTradeAt) / 1000;

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <h1>Binance 실시간 운영 대시보드</h1>
          <p className="sub">BTCUSDT · ETHUSDT 체결/1분봉 수집 파이프라인 모니터</p>
        </div>
        <div className="conn">
          <span className="badge" data-state={state.wsConnected ? "ok" : "down"}>
            {state.wsConnected ? "실시간 연결" : "연결 끊김 (재연결 중)"}
          </span>
          <span className="sub">최근 체결 {formatAge(lastTradeAge)}</span>
        </div>
      </header>

      {warning && <p className="warning">{warning}</p>}

      <nav className="tabs">
        {symbols.map((symbol) => (
          <button
            key={symbol}
            type="button"
            className={symbol === active ? "tab active" : "tab"}
            onClick={() => setActive(symbol)}
          >
            {symbol}
          </button>
        ))}
      </nav>

      <StatCards
        stats={stats}
        lastPrice={symbolState?.lastPrice ?? null}
        takerBuyVolume={symbolState?.takerBuyVolume ?? 0}
        takerSellVolume={symbolState?.takerSellVolume ?? 0}
      />

      <CandleChart symbol={active} candles={symbolState?.candles ?? []} />

      <HealthPanel statuses={health} now={now} />

      <footer className="footer">
        지표 선정 근거는 <code>METRICS.md</code>, 구조·안정성 설계는 <code>README.md</code> 참고.
      </footer>
    </main>
  );
}
