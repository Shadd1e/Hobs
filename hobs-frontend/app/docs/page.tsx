import Link from "next/link";
import { SiteHeader } from "@/components/SiteHeader";

export default function DocsPage() {
  return (
    <>
      <SiteHeader />

      <main className="shell">
        <section className="docs-hero">
          <p className="eyebrow">Documentation</p>
          <h1>What HoBS does</h1>
          <p className="subtitle" style={{ maxWidth: "60ch" }}>
            HoBS is a booking system for hotels and guesthouses that runs on
            WhatsApp. Guests message your existing number to check
            availability, get a price, and pay — HoBS handles the
            conversation and turns it into a confirmed booking.
          </p>
        </section>

        <section className="docs-section">
          <h2>The booking loop</h2>
          <p>
            Every booking follows the same three-step exchange, whether it
            comes from a returning guest or a first-time WhatsApp message:
          </p>
          <div className="how-grid" style={{ marginTop: 24 }}>
            <div className="how-step">
              <span className="how-step-num">01</span>
              <p>A guest asks about a room on WhatsApp — dates, room type, or just &ldquo;anything free tonight?&rdquo;</p>
            </div>
            <div className="how-step">
              <span className="how-step-num">02</span>
              <p>HoBS checks live room availability, quotes a price, and sends a secure payment link in the same chat.</p>
            </div>
            <div className="how-step">
              <span className="how-step-num">03</span>
              <p>Once paid, the booking is marked confirmed and appears on your dashboard — no manual entry.</p>
            </div>
          </div>
        </section>

        <section className="docs-section">
          <h2>What you get on the dashboard</h2>
          <p>Once your hotel is onboarded, you and your staff manage everything from one dashboard:</p>
          <ul className="docs-feature-list">
            <li>
              <strong>Rooms</strong>
              A live grid of every room and whether it&rsquo;s free, booked, or inactive.
            </li>
            <li>
              <strong>Room types</strong>
              Pricing and details for each category of room you offer.
            </li>
            <li>
              <strong>Bookings</strong>
              Every reservation with its status, from pending payment to checked out.
            </li>
            <li>
              <strong>Audit log</strong>
              A record of staff actions, with revert and role controls for managers.
            </li>
          </ul>
        </section>

        <section className="docs-section">
          <h2>Getting your hotel onboarded</h2>
          <p>
            Onboarding is a single application: your contact details, a bit
            about your business, and an identity check. Our team reviews it —
            usually within 1&ndash;2 business days — and emails you a link to
            set your password once approved.
          </p>
          <p style={{ marginTop: 12 }}>
            <Link href="/get-started" className="btn" style={{ display: "inline-flex", width: "auto", padding: "11px 20px" }}>
              Start your application
            </Link>
          </p>
        </section>

        <section className="docs-section" style={{ borderBottom: "1px solid var(--line)" }}>
          <h2>Common questions</h2>
          <dl>
            <div className="faq-item">
              <dt>Do guests need to install anything?</dt>
              <dd>No. They message your existing WhatsApp number like they always have.</dd>
            </div>
            <div className="faq-item">
              <dt>How is payment collected?</dt>
              <dd>Through a secure payment link sent inside the chat — the guest pays before the room is confirmed.</dd>
            </div>
            <div className="faq-item">
              <dt>Can more than one staff member use it?</dt>
              <dd>Yes — staff sign in separately from the hotel owner, and every action they take is recorded in the audit log.</dd>
            </div>
            <div className="faq-item">
              <dt>What if I run more than one hotel?</dt>
              <dd>One login can manage multiple properties — switch between them from the dashboard.</dd>
            </div>
          </dl>
        </section>
      </main>

      <footer className="site-footer">
        <span>© {new Date().getFullYear()} HoBS</span>
        <div className="site-footer-links">
          <Link href="/">Home</Link>
          <Link href="/terms">Terms</Link>
        </div>
      </footer>
    </>
  );
}
