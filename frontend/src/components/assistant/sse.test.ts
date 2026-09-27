import { describe, expect, it } from "vitest";
import { readEvents } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("readEvents", () => {
  it("parses events split across chunks", async () => {
    const events = [];
    for await (const event of readEvents(
      streamOf(['event: delta\ndata: {"text": "При', 'вет"}\n\nevent: done\n', 'data: {"message_id": 3}\n\n']),
    )) {
      events.push(event);
    }
    expect(events).toEqual([
      { event: "delta", data: { text: "Привет" } },
      { event: "done", data: { message_id: 3 } },
    ]);
  });
});
