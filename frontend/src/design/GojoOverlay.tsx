import { readGojoArt } from "./gojoArtStorage";
import "./GojoOverlay.css";

// Easter egg payoff for useGojoEasterEgg — only ever mounted on the "eye"
// design, once the two background blobs have finished converging on the
// held cursor (see App.tsx).
//
// If the user has uploaded their own image via GojoArtUploader (Settings →
// Дизайн, only shown on this design), that's shown instead — sized to a
// fixed zone rather than covering the screen, per the original request.
// No image is ever sourced by this app itself: only a file the user
// explicitly picked from their own disk (see gojoArtStorage.ts) ever ends
// up here. Without an upload, this falls back to the built-in CSS drawing
// below — bold black-ink-on-white shapes (thick outline layers behind the
// fill, same clip-path so they read as an outline), reusing the same blue
// iris color the theme's single eye already uses (--eye-iris in
// EyeDesign.css) so the pair reads as "the same eye, but two of them".
export function GojoOverlay(): JSX.Element {
  const art = readGojoArt();

  if (art) {
    return (
      <div className="gojo-overlay gojo-overlay--custom" aria-hidden="true">
        <img className="gojo-overlay__custom-art" src={art} alt="" />
        <p className="gojo-overlay__caption gojo-overlay__caption--bold">nah I&apos;d win</p>
      </div>
    );
  }

  return (
    <div className="gojo-overlay" aria-hidden="true">
      <div className="gojo-overlay__hair-wrap">
        <div className="gojo-overlay__hair-outline" />
        <div className="gojo-overlay__hair" />
      </div>
      <div className="gojo-overlay__eyes">
        <div className="gojo-overlay__eye">
          <div className="gojo-overlay__eye-outline" />
          <div className="gojo-overlay__sclera" />
          <div className="gojo-overlay__iris">
            <div className="gojo-overlay__pupil" />
            <div className="gojo-overlay__glint" />
          </div>
        </div>
        <div className="gojo-overlay__eye">
          <div className="gojo-overlay__eye-outline" />
          <div className="gojo-overlay__sclera" />
          <div className="gojo-overlay__iris">
            <div className="gojo-overlay__pupil" />
            <div className="gojo-overlay__glint" />
          </div>
        </div>
      </div>
      <p className="gojo-overlay__caption">nah I&apos;d win</p>
    </div>
  );
}
