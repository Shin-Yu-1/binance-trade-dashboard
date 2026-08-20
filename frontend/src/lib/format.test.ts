import { describe, expect, it } from "vitest";

import { formatAge, formatChangePct, formatCompact, formatPrice } from "./format";

describe("formatPrice", () => {
  it("천 단위 구분자와 소수점 2자리로 렌더한다", () => {
    expect(formatPrice(68123.4567)).toBe("68,123.46");
  });

  it("문자열로 온 값(백엔드는 numeric을 문자열로 직렬화)도 처리한다", () => {
    expect(formatPrice("1234.5")).toBe("1,234.50");
  });

  it("값이 없으면 대시를 반환한다", () => {
    expect(formatPrice(null)).toBe("—");
  });
});

describe("formatChangePct", () => {
  it("상승은 부호를 붙여서 표시한다", () => {
    expect(formatChangePct(1.234)).toBe("+1.23%");
  });

  it("하락은 음수 부호를 유지한다", () => {
    expect(formatChangePct(-0.456)).toBe("-0.46%");
  });

  it("값이 없으면 대시를 반환한다", () => {
    expect(formatChangePct(null)).toBe("—");
  });
});

describe("formatCompact", () => {
  it("백만 단위는 M으로 축약한다", () => {
    expect(formatCompact(1_234_567)).toBe("1.23M");
  });

  it("천 단위는 K로 축약한다", () => {
    expect(formatCompact(12_345)).toBe("12.35K");
  });

  it("천 미만은 그대로 소수점 2자리로 표시한다", () => {
    expect(formatCompact(999.5)).toBe("999.50");
  });
});

describe("formatAge", () => {
  it("1초 미만은 '방금'으로 표시한다", () => {
    expect(formatAge(0.4)).toBe("방금");
  });

  it("분 미만은 초 단위로 표시한다", () => {
    expect(formatAge(12.7)).toBe("12초 전");
  });

  it("시간 미만은 분 단위로 표시한다", () => {
    expect(formatAge(305)).toBe("5분 전");
  });

  it("한 시간 이상은 시간 단위로 표시한다", () => {
    expect(formatAge(7_300)).toBe("2시간 전");
  });

  it("수신 기록이 없으면 대시를 반환한다", () => {
    expect(formatAge(null)).toBe("—");
  });
});
