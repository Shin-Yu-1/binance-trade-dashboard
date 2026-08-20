import type { HealthStatus } from "../lib/api";
import { formatAge, formatTimestamp } from "../lib/format";

type Props = {
  statuses: HealthStatus[];
  /** 렌더 시점(ms) — 경과시간 계산을 주입받아 테스트 가능하게 둔다. */
  now: number;
};

type BadgeState = { label: string; state: "ok" | "stale" | "down" };

function badgeFor(status: HealthStatus): BadgeState {
  if (!status.ws_connected) return { label: "끊김", state: "down" };
  if (status.stale) return { label: "지연", state: "stale" };
  return { label: "정상", state: "ok" };
}

function ageSeconds(iso: string | null, now: number): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : (now - ms) / 1000;
}

export function HealthPanel({ statuses, now }: Props) {
  if (statuses.length === 0) {
    return (
      <section className="health-panel">
        <h2>파이프라인 상태</h2>
        <p className="empty">상태 정보를 기다리고 있습니다…</p>
      </section>
    );
  }

  return (
    <section className="health-panel">
      <h2>파이프라인 상태</h2>
      <table>
        <thead>
          <tr>
            <th>심볼</th>
            <th>연결</th>
            <th>마지막 체결</th>
            <th>재연결</th>
            <th>에러</th>
            <th>백필 커버 시작</th>
            <th>마지막 백필</th>
          </tr>
        </thead>
        <tbody>
          {statuses.map((status) => {
            const badge = badgeFor(status);
            return (
              <tr key={status.symbol}>
                <td>{status.symbol}</td>
                <td>
                  <span
                    className="badge"
                    data-state={badge.state}
                    data-testid={`health-badge-${status.symbol}`}
                  >
                    {badge.label}
                  </span>
                </td>
                <td data-testid={`last-trade-age-${status.symbol}`}>
                  {formatAge(ageSeconds(status.last_trade_at, now))}
                </td>
                <td data-testid={`reconnect-count-${status.symbol}`}>{status.reconnect_count}</td>
                <td data-testid={`error-count-${status.symbol}`}>{status.error_count}</td>
                <td data-testid={`backfill-${status.symbol}`}>
                  {formatTimestamp(status.backfill_covered_from)}
                </td>
                <td>{formatTimestamp(status.last_backfill_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
