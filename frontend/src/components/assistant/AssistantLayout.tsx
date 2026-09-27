import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";
import { AssistantHostContext } from "./AssistantHost";
import { AssistantPanel } from "./AssistantPanel";
import { DEFAULT_PANEL_STATE, DEFAULT_PANEL_WIDTH, clampWidth, isNarrow } from "./panelState";
import type { PanelState, PanelStore } from "./panelState";
import type { AssistantContextProvider } from "./types";
import "./AssistantPanel.css";

interface AssistantLayoutProps {
  provider: AssistantContextProvider;
  store: PanelStore;
  children: ReactNode;
}

const KEY_STEP_PX = 24;

function useWindowWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = (): void => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

export function AssistantLayout({ provider, store, children }: AssistantLayoutProps): JSX.Element {
  const [state, setState] = useState<PanelState>(DEFAULT_PANEL_STATE);
  const [dragging, setDragging] = useState(false);
  const windowWidth = useWindowWidth();
  const narrow = isNarrow(windowWidth);
  const width = clampWidth(state.width, windowWidth);
  const layoutRef = useRef<HTMLDivElement>(null);
  const storeRef = useRef(store);
  storeRef.current = store;

  useEffect(() => {
    let cancelled = false;
    storeRef.current
      .load()
      .then((loaded) => {
        if (!cancelled) {
          setState(loaded);
        }
      })
      .catch((error: unknown) => console.error("Failed to load assistant panel state:", error));
    return () => {
      cancelled = true;
    };
  }, []);

  const persist = useCallback((next: PanelState): void => {
    setState(next);
    storeRef.current.save(next).catch((error: unknown) => console.error("Failed to save assistant panel state:", error));
  }, []);

  const toggle = useCallback((): void => {
    setState((current) => {
      const next = { ...current, open: !current.open };
      storeRef.current.save(next).catch((error: unknown) => console.error("Failed to save assistant panel state:", error));
      return next;
    });
  }, []);

  const hide = useCallback((): void => persist({ ...state, open: false }), [persist, state]);

  function widthAt(clientX: number): number {
    const right = layoutRef.current?.getBoundingClientRect().right ?? window.innerWidth;
    return clampWidth(right - clientX, window.innerWidth);
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>): void {
    if (dragging) {
      setState((current) => ({ ...current, width: widthAt(event.clientX) }));
    }
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>): void {
    if (!dragging) {
      return;
    }
    setDragging(false);
    persist({ ...state, width: widthAt(event.clientX) });
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const delta = event.key === "ArrowLeft" ? KEY_STEP_PX : -KEY_STEP_PX;
      persist({ ...state, width: clampWidth(width + delta, window.innerWidth) });
    }
  }

  const host = useMemo(() => ({ open: state.open, toggle }), [state.open, toggle]);

  return (
    <AssistantHostContext.Provider value={host}>
      <div
        ref={layoutRef}
        className={`asst-layout${narrow ? " asst-layout--narrow" : ""}${dragging ? " asst-layout--dragging" : ""}`}
      >
        <div className="asst-layout__content">{children}</div>
        {state.open && !narrow && (
          <div
            className="asst-divider"
            role="separator"
            aria-orientation="vertical"
            aria-label="Изменить ширину панели ассистента"
            aria-valuenow={width}
            tabIndex={0}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onDoubleClick={() => persist({ ...state, width: DEFAULT_PANEL_WIDTH })}
            onKeyDown={onKeyDown}
            data-testid="assistant-divider"
          />
        )}
        {state.open && narrow && (
          <div className="asst-backdrop" onClick={hide} role="presentation" data-testid="assistant-backdrop" />
        )}
        {state.open && (
          <aside
            className={narrow ? "asst-dock asst-dock--overlay" : "asst-dock"}
            style={narrow ? undefined : { width }}
            data-testid="assistant-dock"
          >
            <AssistantPanel provider={provider} onHide={hide} />
          </aside>
        )}
      </div>
    </AssistantHostContext.Provider>
  );
}
