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
    expect(html).toContain('displaystyle="true"');
  });

  it("renders natural-language prose inside the same KaTeX document", () => {
    const html = renderToStaticMarkup(
      createElement(ProblemBody, {
        prompt: "Find the derivative of f(x) = e^{3x} \\cos(x^2).",
      }),
    );
    expect(html).toContain('class="katex"');
    expect(html).toContain("<mtext>Find the derivative of </mtext>");
    expect(html).toContain("<mi>f</mi>");
    expect(html).toContain("<mi>x</mi>");
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

  it("renders raw TeX when the provider omitted dollar delimiters", () => {
    const html = renderToStaticMarkup(
      createElement(ProblemBody, {
        prompt: "Find the derivative of f(x) = e^{3x} \\cos(x^2).",
      }),
    );
    expect(html).toContain('class="katex"');
    expect(html).toContain("e^{3x}");
  });

  it("keeps the complete function clause in the math font", () => {
    expect(
      parseProblemPrompt("Find the derivative of f(x) = e^{3x} \\cos(x^2)."),
    ).toEqual([
      { kind: "text", value: "Find the derivative of " },
      {
        kind: "math",
        value: "f(x) = e^{3x} \\cos(x^2)",
        display: false,
        source: "f(x) = e^{3x} \\cos(x^2)",
      },
      { kind: "text", value: "." },
    ]);
  });
});

it("keeps escaped dollars as text", () => {
  expect(parseProblemPrompt("The fee is \\$5 and $x=5$.")[0]).toEqual({
    kind: "text",
    value: "The fee is $5 and ",
  });
});
