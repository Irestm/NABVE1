import type { DesignComponentProps } from "./types";
import "./GreenCloudDesign.css";

const WISP_COUNT = 6;

export function GreenCloudDesign({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`green-cloud-design green-cloud-design--${state}`} aria-hidden="true">
      <div className="green-cloud-design__halo" />
      <div className="green-cloud-design__mass">
        <span className="green-cloud-design__puff green-cloud-design__puff--1" />
        <span className="green-cloud-design__puff green-cloud-design__puff--2" />
        <span className="green-cloud-design__puff green-cloud-design__puff--3" />
        <span className="green-cloud-design__puff green-cloud-design__puff--4" />
        <span className="green-cloud-design__puff green-cloud-design__puff--5" />
      </div>
      {Array.from({ length: WISP_COUNT }, (_, index) => (
        <div key={index} className={`green-cloud-design__wisp green-cloud-design__wisp--${index}`} />
      ))}
    </div>
  );
}

const FOG_BLOBS = [
  { top: "10%", left: "8%", size: 46, delay: 0, duration: 22 },
  { top: "55%", left: "62%", size: 58, delay: -7, duration: 26 },
  { top: "70%", left: "12%", size: 40, delay: -14, duration: 19 },
  { top: "15%", left: "70%", size: 50, delay: -4, duration: 24 },
];

// Radiation-warning trefoil, tiled faint and sparse across the background —
// "едва заметные значки радиации ... не навязчиво" from the brief. Inline
// data-URI so no extra asset file is needed.
const RADIATION_TILE =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 64 64'%3E%3Cg fill='%2322c55e'%3E%3Ccircle cx='32' cy='32' r='6'/%3E%3Cpath d='M32 32 L32 10 A22 22 0 0 1 51 21 Z'/%3E%3Cpath d='M32 32 L48 43 A22 22 0 0 1 16 43 Z' transform='rotate(0 32 32)'/%3E%3C/g%3E%3C/svg%3E";

// Full-screen dark toxin fog behind the app shell — several large, heavily
// blurred, independently drifting blobs (screen-blended so overlaps read as
// denser vapor) plus a very faint radiation-tile watermark.
export function GreenCloudBackground({ state }: DesignComponentProps): JSX.Element {
  return (
    <div className={`green-cloud-backdrop green-cloud-backdrop--${state}`}>
      <div className="green-cloud-backdrop__base" />
      <div
        className="green-cloud-backdrop__radiation"
        style={{ backgroundImage: `url("${RADIATION_TILE}")` }}
      />
      {FOG_BLOBS.map((blob, index) => (
        <span
          key={index}
          className="green-cloud-backdrop__fog"
          style={{
            top: blob.top,
            left: blob.left,
            width: `${blob.size}vmax`,
            height: `${blob.size}vmax`,
            animationDelay: `${blob.delay}s`,
            animationDuration: `${blob.duration}s`,
          }}
        />
      ))}
    </div>
  );
}
