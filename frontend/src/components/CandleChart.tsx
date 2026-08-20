import {
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { type Candle, toChartCandles } from "../lib/liveState";

type Props = {
  candles: Candle[];
  symbol: string;
};

/**
 * lightweight-charts는 명령형 API라 React state 밖에서 관리한다.
 * 캔들 배열이 바뀌면 setData로 전체를 다시 밀어넣는다 — 1440개 수준에서는
 * 충분히 빠르고, upsert 규칙을 리듀서 한 곳에만 두는 편이 안전하다.
 */
export function CandleChart({ candles, symbol }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "#a7b0c0",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.05)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#26a37b",
      downColor: "#e04f5f",
      borderVisible: false,
      wickUpColor: "#26a37b",
      wickDownColor: "#e04f5f",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(toChartCandles(candles) as unknown as CandlestickData<UTCTimestamp>[]);
  }, [candles]);

  return (
    <section className="chart-card">
      <h2>{symbol} 1분봉</h2>
      <div className="chart" ref={containerRef} data-testid="candle-chart" />
    </section>
  );
}
