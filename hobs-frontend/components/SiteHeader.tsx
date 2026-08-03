import Link from "next/link";
import { Logo } from "./Logo";

/**
 * variant="full"  — home, docs: logo + Docs / Sign in nav.
 * variant="slim"  — the apply wizard: logo only, so the form stays the focus.
 */
export function SiteHeader({ variant = "full" }: { variant?: "full" | "slim" }) {
  return (
    <header className="site-header">
      <Logo />
      {variant === "full" && (
        <nav className="site-nav" aria-label="Site">
          <Link href="/docs">Docs</Link>
          <Link href="/login">Sign in</Link>
        </nav>
      )}
    </header>
  );
}
