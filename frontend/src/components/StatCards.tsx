import { DASH, formatChangePct, formatCompact, formatDirection, formatPrice } from "../lib/format";
import { type DerivedStats, takerBuyRatio } from "../lib/liveState";

type Props = {
  stats: DerivedStats;
  /** 체결 스트림에서 온 최신가 — DB 반영보다 빠르므로 있으면 우선한다. */
  lastPrice: number | null;
  takerBuyVolume: number;
  takerSellVolume: number;
};

export function StatCards({ stats, lastPrice, takerBuyVolume, takerSellVolume }: Props) {
  const price = lastPrice ?? stats.lastPrice;
  const direction = formatDirection(stats.changePct);
  const buyRatio = takerBuyRatio(takerBuyVolume, takerSellVolume);

  return (
    <section className="stat-cards">
      <article className="card">
        <h3>최신가</h3>
        <p className="value" data-testid="last-price">
          {formatPrice(price)}
        </p>
        <p className="sub">체결 스트림 기준</p>
      </article>

      <article className="card">
        <h3>24h 변동률</h3>
        <p className="value" data-testid="change-pct" data-direction={direction}>
          {formatChangePct(stats.changePct)}
        </p>
        <p className="sub">24h 전 1분봉 시가 대비</p>
      </article>

      <article className="card">
        <h3>24h 고가 / 저가</h3>
        <p className="value small" data-testid="high-low">
          {formatPrice(stats.high)} / {formatPrice(stats.low)}
        </p>
        <p className="sub">변동성 범위</p>
      </article>

      <article className="card">
        <h3>24h 거래대금</h3>
        <p className="value" data-testid="quote-volume">
          {formatCompact(stats.quoteVolume)}
        </p>
        <p className="sub">quote volume (USDT)</p>
      </article>

      <article className="card">
        <h3>테이커 매수 비중</h3>
        <p className="value" data-testid="taker-ratio">
          {buyRatio === null ? DASH : `${buyRatio.toFixed(1)}%`}
        </p>
        <div className="pressure-bar" aria-hidden="true">
          <span className="buy" style={{ width: `${buyRatio ?? 50}%` }} />
        </div>
        <p className="sub">24h 집계 + 실시간 누적</p>
      </article>
    </section>
  );
}
