// No dedicated "playing cards" glyph in lucide-react — hand-drawn stand-in:
// a single card outline with corner rank marks and a spade pip (an "ace of
// spades" reads instantly as "cards" at icon size, per request), matching
// lucide's own outline convention (2px stroke, round caps). The pip shape
// itself is the standard typographic spade silhouette, not a reproduction
// of any specific deck's artwork.
export function SolitaireIcon({ size = 24 }: { size?: number }): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect x="4" y="2.5" width="16" height="19" rx="2" strokeWidth="2" />
      <text x="6.5" y="8" fontSize="5.5" fontWeight="700" stroke="none" fill="currentColor">
        A
      </text>
      <path
        d="M12 8.2c-1.8 1.9-4 3.5-4 5.6 0 1.5 1.2 2.5 2.6 2.5 0.6 0 1.1-0.15 1.4-0.4-0.15 1-0.5 1.9-1.4 2.7h3.6c-0.9-0.8-1.25-1.7-1.4-2.7 0.3 0.25 0.8 0.4 1.4 0.4 1.4 0 2.6-1 2.6-2.5 0-2.1-2.2-3.7-4-5.6z"
        fill="currentColor"
        stroke="none"
      />
    </svg>
  );
}
