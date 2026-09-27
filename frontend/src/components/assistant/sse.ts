export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

export function parseBlock(block: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data.push(line.slice(5).trimStart());
    }
  }
  if (data.length === 0) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(data.join("\n"));
    return { event, data: typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {} };
  } catch {
    return null;
  }
}

export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const parsed = parseBlock(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (parsed) {
          yield parsed;
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
    const rest = parseBlock(buffer);
    if (rest) {
      yield rest;
    }
  } finally {
    reader.releaseLock();
  }
}
