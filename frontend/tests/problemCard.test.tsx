import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  parseProblemPrompt,
  ProblemBody,
} from "@/features/problems/ProblemCard";

describe("ProblemBody", () => {
  it("renders inline and display math with KaTeX", () => {
    const html = renderToStaticMarkup(
      <ProblemBody prompt={"Use $x^2$ and then $$\\sum_{n=1}^{\\infty} n^{-2}.$$"} />,
    );
    expect(html).toContain("class=\"katex\"");
    expect(html).toContain("class=\"katex-display\"");
  });

  it("keeps ordinary problem text readable", () => {
    const html = renderToStaticMarkup(
      <ProblemBody prompt="Determine whether the sequence converges." />,
    );
    expect(html).toContain("Determine whether the sequence converges.");
  });

  it("falls back to the original expression when LaTeX is malformed", () => {
    const html = renderToStaticMarkup(<ProblemBody prompt={"Evaluate $\\frac{1$ now."} />);
    expect(html).toContain("data-math-error");
    expect(html).toContain("$\\frac{1$");
  });

  it("never treats problem text as HTML", () => {
    const html = renderToStaticMarkup(
      <ProblemBody prompt={'<img src=x onerror="alert(1)"> $x$'} />,
    );
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });
});

describe("parseProblemPrompt", () => {
  it("keeps escaped dollar signs as text", () => {
    expect(parseProblemPrompt("The fee is \\$5 and $x=5$.")).toEqual([
      { kind: "text", value: "The fee is $5 and " },
      { kind: "math", value: "x=5", display: false, source: "$x=5$" },
      { kind: "text", value: "." },
    ]);
  });

  it("treats an unmatched delimiter as ordinary text", () => {
    expect(parseProblemPrompt("Find $x + 1")).toEqual([
      { kind: "text", value: "Find $x + 1" },
    ]);
  });
});
