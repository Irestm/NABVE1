import type { DesignComponentProps } from "./types";
import "./CalmCloudDesign.css";

export function CalmCloudDesign({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`calm-cloud-design calm-cloud-design--${state}`} aria-hidden="true">
      <div className="calm-cloud-design__halo" />
      <div className="calm-cloud-design__body">
        <span className="calm-cloud-design__puff calm-cloud-design__puff--base" />
        <span className="calm-cloud-design__puff calm-cloud-design__puff--1" />
        <span className="calm-cloud-design__puff calm-cloud-design__puff--2" />
        <span className="calm-cloud-design__puff calm-cloud-design__puff--3" />
        <span className="calm-cloud-design__puff calm-cloud-design__puff--4" />
      </div>
      <span className="calm-cloud-design__spark calm-cloud-design__spark--1" />
      <span className="calm-cloud-design__spark calm-cloud-design__spark--2" />
      <span className="calm-cloud-design__spark calm-cloud-design__spark--3" />
    </div>
  );
}

interface SideCloud {
  top: number;
  side: "left" | "right";
  edge: number;
  scale: number;
  blur: number;
  opacity: number;
  duration: number;
  delay: number;
}

// Depth layered back-to-front: farther clouds are smaller/blurrier/dimmer
// and drift slower - the standard parallax cue - so the sky reads as having
// depth instead of a single cloud floating in a void.
const SIDE_CLOUDS: SideCloud[] = [
  { top: 12, side: "left", edge: -6, scale: 0.55, blur: 2, opacity: 0.35, duration: 46, delay: 0 },
  { top: 28, side: "right", edge: -10, scale: 0.7, blur: 1.4, opacity: 0.45, duration: 38, delay: -8 },
  { top: 48, side: "left", edge: 2, scale: 0.9, blur: 0.6, opacity: 0.6, duration: 30, delay: -4 },
  { top: 62, side: "right", edge: -2, scale: 0.5, blur: 2.4, opacity: 0.3, duration: 52, delay: -20 },
  { top: 78, side: "left", edge: -14, scale: 0.75, blur: 1, opacity: 0.5, duration: 34, delay: -14 },
  { top: 8, side: "right", edge: 6, scale: 1.05, blur: 0.3, opacity: 0.7, duration: 26, delay: -2 },
];

// Full-screen dusk sky behind the app shell, populated with smaller
// parallax clouds along the sides so the main avatar cloud reads as part of
// a sky rather than a lone object in empty space.
export function CalmCloudBackground({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`calm-cloud-backdrop calm-cloud-backdrop--${state}`}>
      <div className="calm-cloud-backdrop__sky" />
      {SIDE_CLOUDS.map((cloud, index) => (
        <div
          key={index}
          className={`calm-cloud-backdrop__cloud calm-cloud-backdrop__cloud--${cloud.side}`}
          style={{
            top: `${cloud.top}%`,
            [cloud.side]: `${cloud.edge}%`,
            transform: `scale(${cloud.scale})`,
            filter: `blur(${cloud.blur}px)`,
            opacity: cloud.opacity,
            animationDuration: `${cloud.duration}s`,
            animationDelay: `${cloud.delay}s`,
          }}
        >
          <span className="calm-cloud-backdrop__puff calm-cloud-backdrop__puff--a" />
          <span className="calm-cloud-backdrop__puff calm-cloud-backdrop__puff--b" />
          <span className="calm-cloud-backdrop__puff calm-cloud-backdrop__puff--c" />
        </div>
      ))}
    </div>
  );
}
