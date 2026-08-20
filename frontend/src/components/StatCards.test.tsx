import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatCards } from "./StatCards";

const stats = {
  lastPrice: 68000,
  changePct: -1.234,
  high: 69000,
  low: 67000,
  volume: 1234.5,
  quoteVolume: 12_345_678,
};

describe("StatCards", () => {
  it("체결 스트림의 최신가를 캔들 종가보다 우선 표시한다", () => {
    render(
      <StatCards stats={stats} lastPrice={68123.45} takerBuyVolume={3} takerSellVolume={1} />,
    );

    expect(screen.getByTestId("last-price")).toHaveTextContent("68,123.45");
  });

  it("캔들만 있으면 마지막 종가를 최신가로 쓴다", () => {
    render(<StatCards stats={stats} lastPrice={null} takerBuyVolume={0} takerSellVolume={0} />);

    expect(screen.getByTestId("last-price")).toHaveTextContent("68,000.00");
  });

  it("24h 변동률을 부호와 함께 표시하고 하락은 down으로 표시한다", () => {
    render(<StatCards stats={stats} lastPrice={null} takerBuyVolume={0} takerSellVolume={0} />);

    const change = screen.getByTestId("change-pct");
    expect(change).toHaveTextContent("-1.23%");
    expect(change).toHaveAttribute("data-direction", "down");
  });

  it("24h 고가/저가/거래량을 표시한다", () => {
    render(<StatCards stats={stats} lastPrice={null} takerBuyVolume={0} takerSellVolume={0} />);

    expect(screen.getByTestId("high-low")).toHaveTextContent("69,000.00");
    expect(screen.getByTestId("high-low")).toHaveTextContent("67,000.00");
    expect(screen.getByTestId("quote-volume")).toHaveTextContent("12.35M");
  });

  it("테이커 매수 비중을 퍼센트로 표시한다", () => {
    render(<StatCards stats={stats} lastPrice={null} takerBuyVolume={3} takerSellVolume={1} />);

    expect(screen.getByTestId("taker-ratio")).toHaveTextContent("75.0%");
  });

  it("데이터가 아직 없으면 대시로 표시하고 깨지지 않는다", () => {
    const empty = {
      lastPrice: null,
      changePct: null,
      high: null,
      low: null,
      volume: null,
      quoteVolume: null,
    };

    render(<StatCards stats={empty} lastPrice={null} takerBuyVolume={0} takerSellVolume={0} />);

    expect(screen.getByTestId("last-price")).toHaveTextContent("—");
    expect(screen.getByTestId("taker-ratio")).toHaveTextContent("—");
  });
});
