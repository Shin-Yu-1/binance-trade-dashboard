import { toNumber } from "./format";

/** 24h(1분봉 1440개)까지만 메모리에 유지한다 — 대시보드가 보여주는 최대 범위. */
export const MAX_CANDLES = 1440;

export type RawCandle = {
  symbol: string;
  open_time: string;
  close_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  quote_volume: string;
  trade_count: number;
  is_closed: boolean;
};

export type RawTrade = {
  time: string;
  symbol: string;
  trade_id: number;
  price: string;
  qty: string;
  quote_qty: string;
  is_buyer_maker: boolean;
};

export type RawTakerStats = {
  taker_buy_volume: string;
  taker_sell_volume: string;
};

export type Candle = {
  openTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  quoteVolume: number;
  tradeCount: number;
  isClosed: boolean;
};

export type SymbolState = {
  lastPrice: number | null;
  lastTradeAt: number | null;
  candles: Candle[];
  takerBuyVolume: number;
  takerSellVolume: number;
};

export type DashboardState = {
  wsConnected: boolean;
  symbols: Record<string, SymbolState>;
};

export type LiveEvent =
  | { type: "candles"; symbol: string; candles: Candle[] }
  | { type: "stats"; symbol: string; stats: RawTakerStats }
  | { type: "trade"; symbol: string; record: RawTrade }
  | { type: "kline"; symbol: string; record: RawCandle }
  | { type: "status"; ws_connected: boolean };

export type DerivedStats = {
  lastPrice: number | null;
  changePct: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  quoteVolume: number | null;
};

const emptySymbolState: SymbolState = {
  lastPrice: null,
  lastTradeAt: null,
  candles: [],
  takerBuyVolume: 0,
  takerSellVolume: 0,
};

export function initialState(symbols: string[]): DashboardState {
  return {
    wsConnected: false,
    symbols: Object.fromEntries(symbols.map((symbol) => [symbol, { ...emptySymbolState }])),
  };
}

export function parseCandle(raw: RawCandle): Candle {
  return {
    openTime: Date.parse(raw.open_time),
    open: Number(raw.open),
    high: Number(raw.high),
    low: Number(raw.low),
    close: Number(raw.close),
    volume: Number(raw.volume),
    quoteVolume: Number(raw.quote_volume),
    tradeCount: raw.trade_count,
    isClosed: raw.is_closed,
  };
}

/** 같은 open_time이면 교체(진행 중 캔들 갱신), 아니면 시간순 삽입 후 링버퍼로 자른다. */
function upsertCandle(candles: Candle[], candle: Candle): Candle[] {
  const index = candles.findIndex((c) => c.openTime === candle.openTime);
  let next: Candle[];
  if (index >= 0) {
    next = [...candles];
    next[index] = candle;
  } else if (candles.length === 0 || candle.openTime > candles[candles.length - 1].openTime) {
    next = [...candles, candle];
  } else {
    next = [...candles, candle].sort((a, b) => a.openTime - b.openTime);
  }
  return trimCandles(next);
}

function trimCandles(candles: Candle[]): Candle[] {
  return candles.length > MAX_CANDLES ? candles.slice(candles.length - MAX_CANDLES) : candles;
}

function withSymbol(
  state: DashboardState,
  symbol: string,
  update: (current: SymbolState) => SymbolState,
): DashboardState {
  const current = state.symbols[symbol];
  // 서버가 우리가 추적하지 않는 심볼을 보내도 조용히 무시한다(같은 참조 → 리렌더 없음).
  if (!current) return state;
  return { ...state, symbols: { ...state.symbols, [symbol]: update(current) } };
}

export function reduce(state: DashboardState, event: LiveEvent): DashboardState {
  switch (event.type) {
    case "status":
      return state.wsConnected === event.ws_connected
        ? state
        : { ...state, wsConnected: event.ws_connected };

    case "candles":
      return withSymbol(state, event.symbol, (current) => ({
        ...current,
        candles: trimCandles(event.candles),
      }));

    case "stats":
      return withSymbol(state, event.symbol, (current) => ({
        ...current,
        takerBuyVolume: toNumber(event.stats.taker_buy_volume) ?? 0,
        takerSellVolume: toNumber(event.stats.taker_sell_volume) ?? 0,
      }));

    case "trade": {
      const qty = Number(event.record.qty);
      // Binance 정의: is_buyer_maker=true → 매수자가 메이커이므로 테이커는 매도 쪽.
      const isTakerBuy = !event.record.is_buyer_maker;
      return withSymbol(state, event.symbol, (current) => ({
        ...current,
        lastPrice: Number(event.record.price),
        lastTradeAt: Date.parse(event.record.time),
        takerBuyVolume: current.takerBuyVolume + (isTakerBuy ? qty : 0),
        takerSellVolume: current.takerSellVolume + (isTakerBuy ? 0 : qty),
      }));
    }

    case "kline": {
      const candle = parseCandle(event.record);
      return withSymbol(state, event.symbol, (current) => ({
        ...current,
        candles: upsertCandle(current.candles, candle),
      }));
    }

    default:
      return state;
  }
}

/**
 * 백엔드 /api/stats와 같은 규칙(첫 시가 → 마지막 종가)으로 계산한다.
 * 실시간 kline이 들어올 때마다 REST 재호출 없이 지표를 갱신하려고 클라이언트에도 둔다.
 */
export function deriveStats(candles: Candle[]): DerivedStats {
  if (candles.length === 0) {
    return {
      lastPrice: null,
      changePct: null,
      high: null,
      low: null,
      volume: null,
      quoteVolume: null,
    };
  }

  const first = candles[0];
  const last = candles[candles.length - 1];
  return {
    lastPrice: last.close,
    changePct: first.open ? ((last.close - first.open) / first.open) * 100 : null,
    high: Math.max(...candles.map((c) => c.high)),
    low: Math.min(...candles.map((c) => c.low)),
    volume: candles.reduce((sum, c) => sum + c.volume, 0),
    quoteVolume: candles.reduce((sum, c) => sum + c.quoteVolume, 0),
  };
}

/** 테이커 매수 체결량 비중(%) — 시장의 매수/매도 압력 지표. */
export function takerBuyRatio(buy: number, sell: number): number | null {
  const total = buy + sell;
  if (total <= 0) return null;
  return (buy / total) * 100;
}

export type ChartCandle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

export function toChartCandles(candles: Candle[]): ChartCandle[] {
  return candles.map((c) => ({
    time: c.openTime / 1000,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}
