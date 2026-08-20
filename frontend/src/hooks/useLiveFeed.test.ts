import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MAX_RECONNECT_DELAY_MS, MIN_RECONNECT_DELAY_MS, useLiveFeed } from "./useLiveFeed";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function createSocket(url: string) {
  return new FakeSocket(url) as unknown as WebSocket;
}

describe("useLiveFeed", () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("수신한 trade 메시지를 대시보드 상태에 반영한다", () => {
    const { result } = renderHook(() => useLiveFeed(["BTCUSDT"], { createSocket }));

    act(() => {
      FakeSocket.instances[0].onopen?.();
      FakeSocket.instances[0].emit({
        type: "trade",
        symbol: "BTCUSDT",
        record: {
          time: "2026-08-20T00:00:01.000Z",
          symbol: "BTCUSDT",
          trade_id: 1,
          price: "68000",
          qty: "1",
          quote_qty: "68000",
          is_buyer_maker: false,
        },
      });
    });

    expect(result.current.state.symbols.BTCUSDT.lastPrice).toBe(68000);
    expect(result.current.state.wsConnected).toBe(true);
  });

  it("연결이 끊기면 wsConnected를 내리고 백오프 후 재연결한다", () => {
    renderHook(() => useLiveFeed(["BTCUSDT"], { createSocket }));

    act(() => {
      FakeSocket.instances[0].onopen?.();
      FakeSocket.instances[0].onclose?.();
    });
    expect(FakeSocket.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(MIN_RECONNECT_DELAY_MS);
    });
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("연속 실패 시 백오프가 2배씩 늘고 상한을 넘지 않는다", () => {
    renderHook(() => useLiveFeed(["BTCUSDT"], { createSocket }));

    let delay = MIN_RECONNECT_DELAY_MS;
    for (let attempt = 1; attempt <= 6; attempt += 1) {
      act(() => {
        FakeSocket.instances[FakeSocket.instances.length - 1].onclose?.();
      });
      act(() => {
        vi.advanceTimersByTime(delay - 1);
      });
      expect(FakeSocket.instances).toHaveLength(attempt);
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(FakeSocket.instances).toHaveLength(attempt + 1);
      delay = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
    }
  });

  it("언마운트 시 소켓을 닫아 누수를 남기지 않는다", () => {
    const { unmount } = renderHook(() => useLiveFeed(["BTCUSDT"], { createSocket }));

    unmount();

    expect(FakeSocket.instances[0].closed).toBe(true);
  });
});
