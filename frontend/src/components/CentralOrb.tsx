import type { CSSProperties } from "react";
import type { AssistantState } from "../types";
import "./CentralOrb.css";

interface CentralOrbProps {
  state: AssistantState;
}

const SPIN_DURATION_SECONDS: Record<AssistantState, number> = {
  idle: 22,
  background_listening: 26,
  listening: 7,
  processing: 5,
  thinking: 3.5,
  speaking: 2.4,
  error: 12,
  paused: 30,
  onboarding: 9,
};

export function CentralOrb({ state }: CentralOrbProps): JSX.Element {
  const style = {
    "--spin-duration": `${SPIN_DURATION_SECONDS[state]}s`,
  } as CSSProperties;

  return (
    <div className={`central-orb central-orb--${state}`} style={style} aria-hidden="true">
      <div className="central-orb__halo" />
      <div className="central-orb__ticks" />
      <div className="central-orb__ring central-orb__ring--outer" />
      <div className="central-orb__ring central-orb__ring--inner" />
      <div className="central-orb__sweep" />
      <div className="central-orb__core">
        <div className="central-orb__core-spin" />
      </div>
    </div>
  );
}
