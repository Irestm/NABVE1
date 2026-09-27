import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatMarkdown } from "./ChatMarkdown";

describe("ChatMarkdown", () => {
  it("renders markdown but never raw HTML or scripts", () => {
    const text = [
      "# Title",
      "**bold** and `code`",
      '<script>window.hacked = true</script><img src="x" onerror="window.hacked = true">',
      "[click](javascript:alert(1))",
      "",
      "| word | level |",
      "| --- | --- |",
      "| grim | B2 |",
    ].join("\n");

    const { container } = render(<ChatMarkdown text={text} />);

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(container.querySelector("h1")?.textContent).toBe("Title");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("table td")?.textContent).toBe("grim");
    const link = container.querySelector("a");
    expect(link?.getAttribute("href") ?? "").not.toContain("javascript");
    expect((window as unknown as { hacked?: boolean }).hacked).toBeUndefined();
  });

  it("highlights fenced code", () => {
    const { container } = render(<ChatMarkdown text={"```python\nprint('hi')\n```"} />);

    expect(container.querySelector("pre code.hljs")).not.toBeNull();
  });
});
