import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { parseProblemPrompt, ProblemBody } from "@/features/problems/ProblemCard";

describe("ProblemBody", () => {
  it("renders inline and display math with KaTeX", () => {
    const html = renderToStaticMarkup(
      createElement(ProblemBody, { prompt: "Use $x^2$ and then $$\\sum_{n=1}^{\\infty} n^{-2}.$$" }),
    );
    expect(html).toContain('class="katex"');
    expect(html).toContain('class="katex-display"');
  });

  it("falls back to readable source when LaTeX is malformed", () => {
    const html = renderToStaticMarkup(
      createElement(ProblemBody, { prompt: "Evaluate $\\frac{1$ now." }),
    );
    expect(html).toContain("data-math-error");
    expect(html).toContain("$\\frac{1$");
  });

  it("does not treat problem text as HTML", () => {
    const html = renderToStaticMarkup(
      createElement(ProblemBody, { prompt: '<img src=x onerror="alert(1)"> $x$' }),
    );
    expect(html).not.toContain("<img");
  });
});

it("keeps escaped dollars as text", () => {
  expect(parseProblemPrompt("The fee is \\$5 and $x=5$.")[0]).toEqual({
    kind: "text",
    value: "The fee is $5 and ",
  });
});
