import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HealthPanel } from "./HealthPanel";
import type { HealthStatus } from "../lib/api";

const now = Date.parse("2026-08-20T00:00:30.000Z");

function status(overrides: Partial<HealthStatus> = {}): HealthStatus {
  return {
    symbol: "BTCUSDT",
    ws_connected: true,
    last_trade_at: "2026-08-20T00:00:28.000Z",
    last_backfill_at: "2026-08-19T23:59:00.000Z",
    backfill_covered_from: "2026-08-19T00:00:00.000Z",
    reconnect_count: 0,
    error_count: 0,
    stale: false,
    ...overrides,
  };
}

describe("HealthPanel", () => {
  it("연결되고 최근 체결이 있으면 정상 상태로 표시한다", () => {
    render(<HealthPanel statuses={[status()]} now={now} />);

    const badge = screen.getByTestId("health-badge-BTCUSDT");
    expect(badge).toHaveTextContent("정상");
    expect(badge).toHaveAttribute("data-state", "ok");
  });

  it("stale 상태는 지연 배지로 경고한다", () => {
    render(<HealthPanel statuses={[status({ stale: true })]} now={now} />);

    const badge = screen.getByTestId("health-badge-BTCUSDT");
    expect(badge).toHaveTextContent("지연");
    expect(badge).toHaveAttribute("data-state", "stale");
  });

  it("WS가 끊기면 끊김 배지로 표시한다", () => {
    render(<HealthPanel statuses={[status({ ws_connected: false, stale: true })]} now={now} />);

    const badge = screen.getByTestId("health-badge-BTCUSDT");
    expect(badge).toHaveTextContent("끊김");
    expect(badge).toHaveAttribute("data-state", "down");
  });

  it("마지막 체결 수신 후 경과시간을 now 기준으로 계산해 보여준다", () => {
    render(<HealthPanel statuses={[status()]} now={now} />);

    expect(screen.getByTestId("last-trade-age-BTCUSDT")).toHaveTextContent("2초 전");
  });

  it("재연결/에러 횟수와 백필 커버 범위를 보여준다", () => {
    render(
      <HealthPanel statuses={[status({ reconnect_count: 3, error_count: 5 })]} now={now} />,
    );

    expect(screen.getByTestId("reconnect-count-BTCUSDT")).toHaveTextContent("3");
    expect(screen.getByTestId("error-count-BTCUSDT")).toHaveTextContent("5");
    expect(screen.getByTestId("backfill-BTCUSDT")).toHaveTextContent("2026");
  });

  it("아직 상태 행이 없으면 안내 문구를 보여준다", () => {
    render(<HealthPanel statuses={[]} now={now} />);

    expect(screen.getByText(/상태 정보를 기다리고 있습니다/)).toBeInTheDocument();
  });
});
