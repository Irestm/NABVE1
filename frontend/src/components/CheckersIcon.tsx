// No two-tone "one white, one black piece" icon exists in lucide-react
// (its icons are single-color, driven by currentColor) — this is a small
// hand-drawn stand-in, same viewBox/stroke convention lucide icons use, so
// it drops into the same size={N} call sites (CommandPanel, BoardGamesPanel)
// without special-casing.
export function CheckersIcon({ size = 24 }: { size?: number }): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <circle cx="6.5" cy="12" r="5" fill="#f5f7fb" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="17.5" cy="12" r="5" fill="#111318" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
