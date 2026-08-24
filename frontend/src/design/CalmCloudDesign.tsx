import type { CSSProperties } from "react";
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
  // Each cloud owns a fixed vertical lane (top %) wide enough apart from
  // its neighbors that, combined with its own scaled height, it can never
  // vertically overlap another cloud while crossing — that's the whole
  // "не наслаиваются" guarantee, enforced by layout rather than by
  // tracking live positions. Only the main avatar cloud (a separate
  // component, CalmCloudDesign above) sits outside this lane system, so
  // it's naturally exempt.
  top: number;
  side: "left" | "right";
  scale: number;
  blur: number;
  opacity: number;
  duration: number;
  delay: number;
}

// Depth layered back-to-front: farther clouds are smaller/blurrier/dimmer
// and cross slower - the standard parallax cue - so the sky reads as having
// depth instead of a single cloud floating in a void. Durations/delays are
// deliberately uneven (not evenly spaced) and directions alternate so the
// crossings read as "постоянно в случайном порядке" rather than a
// synchronized wave all moving together. Durations tuned to land clearly
// 15 clouds now (10 x1.5, explicit "ещё больше облачков в раза 1.5") —
// 15 lanes, ~6.5% apart. Durations kept in the same slow 70-150s range
// established by the two prior speed rounds; scale trimmed slightly at
// the top end (was up to 0.95, now up to 0.85) so even the biggest cloud
// stays comfortably inside its now-narrower lane band.
const SIDE_CLOUDS: SideCloud[] = [
  { top: 2, side: "left", scale: 0.5, blur: 2, opacity: 0.32, duration: 130, delay: -30 },
  { top: 8.5, side: "right", scale: 0.6, blur: 1.6, opacity: 0.38, duration: 100, delay: -60 },
  { top: 15, side: "left", scale: 0.65, blur: 1.4, opacity: 0.42, duration: 96, delay: -70 },
  { top: 21.5, side: "right", scale: 0.75, blur: 1, opacity: 0.5, duration: 85, delay: -20 },
  { top: 28, side: "left", scale: 0.8, blur: 0.6, opacity: 0.58, duration: 80, delay: -16 },
  { top: 34.5, side: "right", scale: 0.5, blur: 2.2, opacity: 0.3, duration: 140, delay: -95 },
  { top: 41, side: "left", scale: 0.45, blur: 2.4, opacity: 0.28, duration: 150, delay: -110 },
  { top: 47.5, side: "right", scale: 0.7, blur: 1, opacity: 0.48, duration: 90, delay: -46 },
  { top: 54, side: "left", scale: 0.6, blur: 1.6, opacity: 0.4, duration: 105, delay: -75 },
  { top: 60.5, side: "right", scale: 0.85, blur: 0.3, opacity: 0.68, duration: 70, delay: -90 },
  { top: 67, side: "left", scale: 0.55, blur: 1.8, opacity: 0.36, duration: 120, delay: -6 },
  { top: 73.5, side: "right", scale: 0.65, blur: 1.4, opacity: 0.44, duration: 98, delay: -52 },
  { top: 80, side: "left", scale: 0.75, blur: 0.8, opacity: 0.55, duration: 86, delay: -56 },
  { top: 86.5, side: "right", scale: 0.6, blur: 1.6, opacity: 0.4, duration: 110, delay: -80 },
  { top: 93, side: "left", scale: 0.8, blur: 0.5, opacity: 0.62, duration: 76, delay: -26 },
];

// Full-screen dusk sky behind the app shell, with smaller parallax clouds
// continuously crossing it edge-to-edge (each in its own lane, see
// SideCloud above) so the main avatar cloud reads as part of a living sky
// rather than a lone object in empty space.
export function CalmCloudBackground({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`calm-cloud-backdrop calm-cloud-backdrop--${state}`}>
      <div className="calm-cloud-backdrop__sky" />
      {SIDE_CLOUDS.map((cloud, index) => (
        <div
          key={index}
          className={`calm-cloud-backdrop__cloud calm-cloud-backdrop__cloud--${cloud.side}`}
          style={
            {
              top: `${cloud.top}%`,
              [cloud.side]: 0,
              "--cloud-scale": cloud.scale,
              filter: `blur(${cloud.blur}px)`,
              opacity: cloud.opacity,
              animationDuration: `${cloud.duration}s`,
              animationDelay: `${cloud.delay}s`,
            } as CSSProperties
          }
        >
          <span className="calm-cloud-backdrop__puff calm-cloud-backdrop__puff--a" />
          <span className="calm-cloud-backdrop__puff calm-cloud-backdrop__puff--b" />
          <span className="calm-cloud-backdrop__puff calm-cloud-backdrop__puff--c" />
        </div>
      ))}
    </div>
  );
}
