/// <reference types="@figma/plugin-typings" />

// Jarvis Voice Control — Figma plugin main (sandboxed) thread.
//
// This file owns all figma.* Plugin API calls. It does NOT hold the
// WebSocket itself — the plugin sandbox has no WebSocket/fetch of its own,
// only the UI iframe (ui.html) does, since that's a real browser context.
// figma.showUI(..., { visible: false }) starts that iframe hidden in the
// background purely as a transport relay: ui.html owns the socket to the
// Jarvis backend (modules/figma_control/ws_server.py) and forwards raw
// JSON both ways via postMessage. See ui.html's top comment for the other
// half of this split.

// Figma's plugin sandbox provides btoa (documented specifically for
// base64-encoding exportAsync's raw bytes, since there's no Buffer or
// TextEncoder here) but the "ES2017" lib alone doesn't declare it — adding
// "dom" to tsconfig.json's lib instead would pull in a much larger surface
// that conflicts with @figma/plugin-typings' own Node/CanvasNode etc.
declare function btoa(data: string): string;

figma.showUI(__html__, { visible: false, width: 0, height: 0 });

type IncomingCommand = {
  request_id?: string;
  action: string;
  params: Record<string, unknown>;
};

type ActionResult = {
  status: "success" | "error" | "unsupported";
  message: string;
  result?: Record<string, unknown>;
};

// ---- color parsing -------------------------------------------------------

// modules/figma_control/command_parser.py already resolves a spoken color
// name ("красный") to a hex string before it ever reaches this plugin, so
// this only needs to understand the wire format: a "#rrggbb"/"rrggbb" hex
// string, or an already-split {r,g,b} object (0-255 or 0-1 — both accepted
// so the Python side doesn't have to guess which scale this expects).
function parseColor(input: unknown): RGB {
  if (typeof input === "string") {
    const hex = input.trim().replace(/^#/, "");
    if (/^[0-9a-fA-F]{6}$/.test(hex)) {
      return {
        r: parseInt(hex.slice(0, 2), 16) / 255,
        g: parseInt(hex.slice(2, 4), 16) / 255,
        b: parseInt(hex.slice(4, 6), 16) / 255,
      };
    }
    throw new Error(`Unrecognized color value: '${input}'`);
  }
  if (input && typeof input === "object") {
    const raw = input as Record<string, number>;
    const scale = raw.r > 1 || raw.g > 1 || raw.b > 1 ? 255 : 1;
    return { r: raw.r / scale, g: raw.g / scale, b: raw.b / scale };
  }
  throw new Error("Missing or invalid 'color'/'fill_color' parameter");
}

// ---- layer lookup ---------------------------------------------------------

function findLayerByName(layerName: unknown): SceneNode {
  if (typeof layerName !== "string" || !layerName.trim()) {
    throw new Error("Missing required parameter 'layer_name'");
  }
  const node = figma.currentPage.findOne((n) => n.name === layerName);
  if (!node) {
    throw new Error(`Layer named '${layerName}' was not found on the current page`);
  }
  return node;
}

function requireNumber(params: Record<string, unknown>, key: string): number {
  const value = params[key];
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new Error(`Missing or invalid required parameter '${key}'`);
  }
  return value;
}

// ---- action handlers --------------------------------------------------

async function createRectangle(params: Record<string, unknown>): Promise<ActionResult> {
  const rect = figma.createRectangle();
  rect.x = typeof params.x === "number" ? params.x : figma.viewport.center.x;
  rect.y = typeof params.y === "number" ? params.y : figma.viewport.center.y;
  rect.resize(requireNumber(params, "width"), requireNumber(params, "height"));
  if (params.fill_color !== undefined) {
    rect.fills = [{ type: "SOLID", color: parseColor(params.fill_color) }];
  }
  figma.currentPage.selection = [rect];
  figma.viewport.scrollAndZoomIntoView([rect]);
  return { status: "success", message: "Прямоугольник создан.", result: { name: rect.name } };
}

async function createText(params: Record<string, unknown>): Promise<ActionResult> {
  const content = params.content;
  if (typeof content !== "string" || !content) {
    throw new Error("Missing required parameter 'content'");
  }
  const fontSize = typeof params.font_size === "number" ? params.font_size : 16;
  const font: FontName = { family: "Inter", style: "Regular" };
  await figma.loadFontAsync(font);
  const text = figma.createText();
  text.fontName = font;
  text.fontSize = fontSize;
  text.characters = content;
  text.x = typeof params.x === "number" ? params.x : figma.viewport.center.x;
  text.y = typeof params.y === "number" ? params.y : figma.viewport.center.y;
  figma.currentPage.selection = [text];
  figma.viewport.scrollAndZoomIntoView([text]);
  return { status: "success", message: "Текст создан.", result: { name: text.name } };
}

async function createFrame(params: Record<string, unknown>): Promise<ActionResult> {
  const frame = figma.createFrame();
  frame.x = typeof params.x === "number" ? params.x : figma.viewport.center.x;
  frame.y = typeof params.y === "number" ? params.y : figma.viewport.center.y;
  frame.resize(requireNumber(params, "width"), requireNumber(params, "height"));
  if (typeof params.name === "string" && params.name) {
    frame.name = params.name;
  }
  figma.currentPage.selection = [frame];
  figma.viewport.scrollAndZoomIntoView([frame]);
  return { status: "success", message: "Фрейм создан.", result: { name: frame.name } };
}

async function selectLayer(params: Record<string, unknown>): Promise<ActionResult> {
  const node = findLayerByName(params.layer_name);
  figma.currentPage.selection = [node];
  figma.viewport.scrollAndZoomIntoView([node]);
  return { status: "success", message: `Слой '${node.name}' выделен.`, result: { name: node.name } };
}

async function moveLayer(params: Record<string, unknown>): Promise<ActionResult> {
  const node = findLayerByName(params.layer_name);
  const name = node.name;
  if (!("x" in node) || !("y" in node)) {
    throw new Error(`Layer '${name}' does not support repositioning`);
  }
  (node as LayoutMixin).x = requireNumber(params, "x");
  (node as LayoutMixin).y = requireNumber(params, "y");
  return { status: "success", message: `Слой '${name}' перемещён.` };
}

async function resizeLayer(params: Record<string, unknown>): Promise<ActionResult> {
  const node = findLayerByName(params.layer_name);
  const name = node.name;
  if (!("resize" in node)) {
    throw new Error(`Layer '${name}' does not support resizing`);
  }
  (node as LayoutMixin).resize(requireNumber(params, "width"), requireNumber(params, "height"));
  return { status: "success", message: `Размер слоя '${name}' изменён.` };
}

async function changeColor(params: Record<string, unknown>): Promise<ActionResult> {
  const node = findLayerByName(params.layer_name);
  const name = node.name;
  if (!("fills" in node)) {
    throw new Error(`Layer '${name}' has no fill to change`);
  }
  const color = parseColor(params.color ?? params.fill_color);
  (node as MinimalFillsMixin).fills = [{ type: "SOLID", color }];
  return { status: "success", message: `Цвет слоя '${name}' изменён.` };
}

async function groupSelection(_params: Record<string, unknown>): Promise<ActionResult> {
  const selection = figma.currentPage.selection;
  if (selection.length === 0) {
    throw new Error("Nothing is selected to group");
  }
  const group = figma.group(selection, figma.currentPage);
  figma.currentPage.selection = [group];
  return { status: "success", message: "Слои сгруппированы.", result: { name: group.name } };
}

const ALIGNMENTS = new Set(["left", "right", "center_horizontal", "top", "bottom", "center_vertical"]);

async function align(params: Record<string, unknown>): Promise<ActionResult> {
  const alignment = params.alignment;
  if (typeof alignment !== "string" || !ALIGNMENTS.has(alignment)) {
    throw new Error(`'alignment' must be one of: ${Array.from(ALIGNMENTS).join(", ")}`);
  }
  const selection = figma.currentPage.selection.filter(
    (n): n is SceneNode & LayoutMixin => "x" in n && "y" in n && "width" in n,
  );
  if (selection.length < 1) {
    throw new Error("Nothing selected to align");
  }
  const minX = Math.min(...selection.map((n) => n.x));
  const maxX = Math.max(...selection.map((n) => n.x + n.width));
  const minY = Math.min(...selection.map((n) => n.y));
  const maxY = Math.max(...selection.map((n) => n.y + n.height));

  for (const node of selection) {
    switch (alignment) {
      case "left":
        node.x = minX;
        break;
      case "right":
        node.x = maxX - node.width;
        break;
      case "center_horizontal":
        node.x = (minX + maxX) / 2 - node.width / 2;
        break;
      case "top":
        node.y = minY;
        break;
      case "bottom":
        node.y = maxY - node.height;
        break;
      case "center_vertical":
        node.y = (minY + maxY) / 2 - node.height / 2;
        break;
    }
  }
  return { status: "success", message: "Выравнивание выполнено." };
}

async function deleteLayer(params: Record<string, unknown>): Promise<ActionResult> {
  const node = findLayerByName(params.layer_name);
  const name = node.name;
  node.remove();
  return { status: "success", message: `Слой '${name}' удалён.` };
}

async function exportSelection(params: Record<string, unknown>): Promise<ActionResult> {
  const selection = figma.currentPage.selection;
  if (selection.length === 0) {
    throw new Error("Nothing is selected to export");
  }
  const format = (typeof params.format === "string" ? params.format.toUpperCase() : "PNG") as
    | "PNG"
    | "JPG"
    | "SVG"
    | "PDF";
  const exported: { name: string; data: string }[] = [];
  for (const node of selection) {
    const bytes = await node.exportAsync({ format });
    // WebSocket JSON has no native binary type here — base64 is the
    // simplest thing every consumer (Python's ws_server / dispatcher) can
    // decode without a second protocol.
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    exported.push({ name: node.name, data: btoa(binary) });
  }
  return {
    status: "success",
    message: `Экспортировано слоёв: ${exported.length}.`,
    result: { format, files: exported },
  };
}

// Figma's Plugin API has no programmatic undo/redo — only the user-facing
// Ctrl+Z/Ctrl+Shift+Z editor shortcuts exist, which this sandbox can't
// invoke. Reported as unsupported so modules/figma_control/dispatcher.py
// falls back to screen_fallback.py's keyboard-shortcut path instead.
async function unsupportedUndoRedo(_params: Record<string, unknown>): Promise<ActionResult> {
  return { status: "unsupported", message: "Undo/redo is not available via the Figma Plugin API." };
}

const HANDLERS: Record<string, (params: Record<string, unknown>) => Promise<ActionResult>> = {
  create_rectangle: createRectangle,
  create_text: createText,
  create_frame: createFrame,
  select_layer: selectLayer,
  move_layer: moveLayer,
  resize_layer: resizeLayer,
  change_color: changeColor,
  group_selection: groupSelection,
  align: align,
  delete_layer: deleteLayer,
  export_selection: exportSelection,
  undo: unsupportedUndoRedo,
  redo: unsupportedUndoRedo,
};

async function handleAction(action: string, params: Record<string, unknown>): Promise<ActionResult> {
  const handler = HANDLERS[action];
  if (!handler) {
    return { status: "unsupported", message: `Unknown action '${action}'.` };
  }
  return handler(params);
}

figma.ui.onmessage = async (msg: { type?: string; payload?: IncomingCommand }) => {
  if (!msg || msg.type !== "ws-command" || !msg.payload) return;
  const command = msg.payload;
  let result: ActionResult;
  try {
    result = await handleAction(command.action, command.params || {});
  } catch (err) {
    result = { status: "error", message: err instanceof Error ? err.message : String(err) };
  }
  figma.ui.postMessage({
    type: "ws-send",
    payload: {
      request_id: command.request_id,
      status: result.status,
      message: result.message,
      result: result.result ?? {},
    },
  });
};
