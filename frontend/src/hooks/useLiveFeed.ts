import { useEffect, useReducer, useRef } from "react";

import { type LiveEvent, initialState, reduce } from "../lib/liveState";

export const MIN_RECONNECT_DELAY_MS = 1_000;
export const MAX_RECONNECT_DELAY_MS = 15_000;

type Options = {
  /** 테스트에서 가짜 소켓을 주입하기 위한 팩토리. */
  createSocket?: (url: string) => WebSocket;
  url?: string;
};

function defaultUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/live`;
}

function defaultCreateSocket(url: string): WebSocket {
  return new WebSocket(url);
}

/**
 * /ws/live 구독을 관리한다. 끊기면 지수 백오프로 계속 재연결하고,
 * 연결이 없는 동안에도 마지막으로 받은 상태는 그대로 유지한다
 * (빈 화면 대신 "끊김" 배지 + 마지막 값 표시).
 */
export function useLiveFeed(symbols: string[], options: Options = {}) {
  const [state, dispatch] = useReducer(reduce, symbols, initialState);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const symbolKey = symbols.join(",");

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let delay = MIN_RECONNECT_DELAY_MS;

    const scheduleReconnect = () => {
      if (stopped) return;
      const wait = delay;
      delay = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
      timer = setTimeout(connect, wait);
    };

    function connect() {
      if (stopped) return;
      const create = optionsRef.current.createSocket ?? defaultCreateSocket;
      const url = optionsRef.current.url ?? defaultUrl();
      const next = create(url);
      socket = next;

      next.onopen = () => {
        delay = MIN_RECONNECT_DELAY_MS;
        dispatch({ type: "status", ws_connected: true });
      };
      next.onmessage = (event: MessageEvent) => {
        try {
          dispatch(JSON.parse(event.data as string) as LiveEvent);
        } catch {
          // 깨진 프레임 하나가 스트림 전체를 죽이지 않게 조용히 버린다.
        }
      };
      next.onclose = () => {
        dispatch({ type: "status", ws_connected: false });
        scheduleReconnect();
      };
    }

    connect();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [symbolKey]);

  return { state, dispatch };
}
