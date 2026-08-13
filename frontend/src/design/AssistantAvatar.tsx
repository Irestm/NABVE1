import { useRef } from "react";
import type { AssistantState } from "../types";
import { useAmplitude } from "../hooks/useAmplitude";
import { getDesign } from "./registry";
import type { DesignId } from "./types";
import "./AssistantAvatar.css";

interface AssistantAvatarProps {
  state: AssistantState;
  designId: DesignId;
}

// Replaces the old bare <CentralOrb> in App.tsx. Owns the one shared
// --amplitude CSS variable (see useAmplitude) on a wrapper element so every
// design underneath can react to it in plain CSS without each one wiring up
// its own analyser — the "sun expands with your voice" behavior from point 1
// of the design-picker request falls out of this for free for any design
// that chooses to read var(--amplitude).
export function AssistantAvatar({ state, designId }: AssistantAvatarProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  useAmplitude(containerRef, state);

  const design = getDesign(designId);
  const Component = design.Component;

  return (
    <div ref={containerRef} className="assistant-avatar">
      <Component state={state} />
    </div>
  );
}
