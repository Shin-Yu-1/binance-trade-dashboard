import { describe, expect, it } from "vitest";

import {
  MAX_CANDLES,
  type RawCandle,
  type RawTrade,
  deriveStats,
  initialState,
  parseCandle,
  reduce,
  takerBuyRatio,
  toChartCandles,
} from "./liveState";

function rawCandle(openTimeMs: number, overrides: Partial<RawCandle> = {}): RawCandle {
  return {
    symbol: "BTCUSDT",
    open_time: new Date(openTimeMs).toISOString(),
    close_time: new Date(openTimeMs + 59_999).toISOString(),
    open: "100",
    high: "110",
    low: "90",
    close: "105",
    volume: "2",
    quote_volume: "210",
    trade_count: 7,
    is_closed: true,
    ...overrides,
  };
}

function rawTrade(overrides: Partial<RawTrade> = {}): RawTrade {
  return {
    time: "2026-08-20T00:00:10.000Z",
    symbol: "BTCUSDT",
    trade_id: 1,
    price: "101.5",
    qty: "0.5",
    quote_qty: "50.75",
    is_buyer_maker: false,
    ...overrides,
  };
}

describe("parseCandle", () => {
  it("문자열 numeric과 ISO 시각을 숫자/에폭 ms로 변환한다", () => {
    const candle = parseCandle(rawCandle(Date.UTC(2026, 7, 20, 0, 0)));

    expect(candle).toEqual({
      openTime: Date.UTC(2026, 7, 20, 0, 0),
      open: 100,
      high: 110,
      low: 90,
      close: 105,
      volume: 2,
      quoteVolume: 210,
      tradeCount: 7,
      isClosed: true,
    });
  });
});

describe("reduce", () => {
  const symbols = ["BTCUSDT", "ETHUSDT"];

  it("trade 이벤트가 해당 심볼의 최신가와 수신 시각만 갱신한다", () => {
    const next = reduce(initialState(symbols), {
      type: "trade",
      symbol: "BTCUSDT",
      record: rawTrade({ price: "68000.1" }),
    });

    expect(next.symbols.BTCUSDT.lastPrice).toBe(68000.1);
    expect(next.symbols.BTCUSDT.lastTradeAt).toBe(Date.parse("2026-08-20T00:00:10.000Z"));
    expect(next.symbols.ETHUSDT.lastPrice).toBeNull();
  });

  it("is_buyer_maker로 테이커 매수/매도 체결량을 나눠 누적한다", () => {
    // Binance 정의: is_buyer_maker=true면 매수자가 메이커 → 테이커는 매도 쪽.
    let state = initialState(symbols);
    state = reduce(state, {
      type: "trade",
      symbol: "BTCUSDT",
      record: rawTrade({ qty: "1.5", is_buyer_maker: false }),
    });
    state = reduce(state, {
      type: "trade",
      symbol: "BTCUSDT",
      record: rawTrade({ qty: "0.5", is_buyer_maker: true }),
    });

    expect(state.symbols.BTCUSDT.takerBuyVolume).toBe(1.5);
    expect(state.symbols.BTCUSDT.takerSellVolume).toBe(0.5);
  });

  it("kline 이벤트가 같은 open_time의 진행 중 캔들을 중복 없이 교체한다", () => {
    const openTime = Date.UTC(2026, 7, 20, 0, 5);
    let state = reduce(initialState(symbols), {
      type: "kline",
      symbol: "BTCUSDT",
      record: rawCandle(openTime, { close: "105", is_closed: false }),
    });
    state = reduce(state, {
      type: "kline",
      symbol: "BTCUSDT",
      record: rawCandle(openTime, { close: "107", is_closed: true }),
    });

    expect(state.symbols.BTCUSDT.candles).toHaveLength(1);
    expect(state.symbols.BTCUSDT.candles[0].close).toBe(107);
    expect(state.symbols.BTCUSDT.candles[0].isClosed).toBe(true);
  });

  it("새 open_time의 kline은 시간순으로 뒤에 붙는다", () => {
    let state = reduce(initialState(symbols), {
      type: "candles",
      symbol: "BTCUSDT",
      candles: [parseCandle(rawCandle(Date.UTC(2026, 7, 20, 0, 0)))],
    });
    state = reduce(state, {
      type: "kline",
      symbol: "BTCUSDT",
      record: rawCandle(Date.UTC(2026, 7, 20, 0, 1)),
    });

    expect(state.symbols.BTCUSDT.candles.map((c) => c.openTime)).toEqual([
      Date.UTC(2026, 7, 20, 0, 0),
      Date.UTC(2026, 7, 20, 0, 1),
    ]);
  });

  it("추적하지 않는 심볼의 이벤트는 무시하고 같은 상태를 반환한다", () => {
    const state = initialState(symbols);
    const next = reduce(state, {
      type: "trade",
      symbol: "SOLUSDT",
      record: rawTrade({ symbol: "SOLUSDT" }),
    });

    expect(next).toBe(state);
  });

  it("캔들은 MAX_CANDLES 개수를 넘으면 가장 오래된 것부터 버린다", () => {
    const base = Date.UTC(2026, 7, 20, 0, 0);
    const candles = Array.from({ length: MAX_CANDLES }, (_, i) =>
      parseCandle(rawCandle(base + i * 60_000)),
    );
    let state = reduce(initialState(symbols), { type: "candles", symbol: "BTCUSDT", candles });
    state = reduce(state, {
      type: "kline",
      symbol: "BTCUSDT",
      record: rawCandle(base + MAX_CANDLES * 60_000),
    });

    expect(state.symbols.BTCUSDT.candles).toHaveLength(MAX_CANDLES);
    expect(state.symbols.BTCUSDT.candles[0].openTime).toBe(base + 60_000);
  });

  it("status 이벤트가 WS 연결 상태를 갱신한다", () => {
    const state = reduce(initialState(symbols), { type: "status", ws_connected: false });

    expect(state.wsConnected).toBe(false);
  });

  it("stats 이벤트가 24h 테이커 체결량을 초기값으로 심는다", () => {
    const state = reduce(initialState(symbols), {
      type: "stats",
      symbol: "BTCUSDT",
      stats: { taker_buy_volume: "10", taker_sell_volume: "6" },
    });

    expect(state.symbols.BTCUSDT.takerBuyVolume).toBe(10);
    expect(state.symbols.BTCUSDT.takerSellVolume).toBe(6);
  });

  it("심어진 24h 테이커 체결량 위에 실시간 체결이 누적된다", () => {
    let state = reduce(initialState(symbols), {
      type: "stats",
      symbol: "BTCUSDT",
      stats: { taker_buy_volume: "10", taker_sell_volume: "6" },
    });
    state = reduce(state, {
      type: "trade",
      symbol: "BTCUSDT",
      record: rawTrade({ qty: "2", is_buyer_maker: false }),
    });

    expect(state.symbols.BTCUSDT.takerBuyVolume).toBe(12);
  });
});

describe("toChartCandles", () => {
  it("lightweight-charts가 쓰는 초 단위 time과 OHLC로 매핑한다", () => {
    const openTime = Date.UTC(2026, 7, 20, 0, 0);
    const candles = [parseCandle(rawCandle(openTime))];

    expect(toChartCandles(candles)).toEqual([
      { time: openTime / 1000, open: 100, high: 110, low: 90, close: 105 },
    ]);
  });
});

describe("deriveStats", () => {
  it("첫 캔들 시가 대비 마지막 종가로 변동률과 고저·거래량을 계산한다", () => {
    const candles = [
      parseCandle(rawCandle(0, { open: "100", high: "120", low: "95", volume: "3" })),
      parseCandle(rawCandle(60_000, { open: "105", high: "115", low: "90", close: "110", volume: "2" })),
    ];

    expect(deriveStats(candles)).toEqual({
      lastPrice: 110,
      changePct: 10,
      high: 120,
      low: 90,
      volume: 5,
      quoteVolume: 420,
    });
  });

  it("캔들이 없으면 모든 지표가 null이다", () => {
    expect(deriveStats([])).toEqual({
      lastPrice: null,
      changePct: null,
      high: null,
      low: null,
      volume: null,
      quoteVolume: null,
    });
  });
});

describe("takerBuyRatio", () => {
  it("전체 체결량 중 테이커 매수 비중을 퍼센트로 계산한다", () => {
    expect(takerBuyRatio(3, 1)).toBe(75);
  });

  it("체결이 없으면 null이다", () => {
    expect(takerBuyRatio(0, 0)).toBeNull();
  });
});
