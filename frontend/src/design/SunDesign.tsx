import type { DesignComponentProps } from "./types";
import "./SunDesign.css";

export function SunDesign({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`sun-design sun-design--${state}`} aria-hidden="true">
      <div className="sun-design__corona" />
      <div className="sun-design__flares" />
      <div className="sun-design__flares sun-design__flares--reverse" />
      <div className="sun-design__surface">
        <div className="sun-design__granules" />
        <div className="sun-design__glint" />
      </div>
    </div>
  );
}

// Full-screen sky behind the app shell — a warm radial glow around a fixed
// high zenith point plus two slow-spinning ray bands, replacing the generic
// HUD grid (see ThemeBackdrop). Intensity/brightness step per state instead
// of continuous --amplitude — see design/ThemeBackdrop.tsx for why.
export function SunBackground({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`sun-backdrop sun-backdrop--${state}`}>
      <div className="sun-backdrop__sky" />
      <div className="sun-backdrop__rays" />
      <div className="sun-backdrop__rays sun-backdrop__rays--reverse" />
    </div>
  );
}
