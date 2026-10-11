import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MarkdownText } from "./markdown";

describe("MarkdownText", () => {
  it("renders emphasis and a bulleted list instead of literal markdown markers", () => {
    const html = renderToStaticMarkup(
      <MarkdownText content={"**NVDA** looks *volatile*.\n\n- Watch valuation\n- Review sources"} />,
    );

    expect(html).toContain("<strong>NVDA</strong>");
    expect(html).toContain("<em>volatile</em>");
    expect(html).toContain("<ul>");
    expect(html).not.toContain("**NVDA**");
  });
});
