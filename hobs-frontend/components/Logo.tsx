import Link from "next/link";

/** Brand mark: the same shape as app/icon.svg (favicon), rendered inline so
 * it can inherit currentColor and sit next to the wordmark in the header. */
export function Logo({ withWord = true }: { withWord?: boolean }) {
  return (
    <Link href="/" className="brand" aria-label="HoBS — home">
      <svg
        className="brand-mark"
        viewBox="0 0 64 64"
        width="26"
        height="26"
        aria-hidden="true"
      >
        <rect x="4" y="4" width="56" height="56" rx="16" fill="currentColor" />
        <circle cx="4" cy="32" r="6" fill="var(--paper)" />
        <circle cx="60" cy="32" r="6" fill="var(--paper)" />
        <rect x="18" y="18" width="8" height="28" fill="var(--paper)" />
        <rect x="38" y="18" width="8" height="28" fill="var(--paper)" />
        <rect x="18" y="28" width="28" height="8" fill="var(--paper)" />
      </svg>
      {withWord && <span className="brand-word">HoBS</span>}
    </Link>
  );
}
