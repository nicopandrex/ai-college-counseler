import { describe, expect, it } from "vitest";
import { termName } from "./format";

describe("termName", () => {
  it("spells out the season of a term code", () => {
    expect(termName("2027SP")).toBe("Spring 2027");
    expect(termName("2026FA")).toBe("Fall 2026");
  });

  it("leaves an unknown code as it is", () => {
    expect(termName("202701")).toBe("202701");
  });
});
