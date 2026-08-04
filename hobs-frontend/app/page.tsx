import Link from "next/link";

function IconMessage() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7A2.5 2.5 0 0 1 17.5 15H10l-4.5 4V15h-1A2.5 2.5 0 0 1 2 12.5v-5" />
      <path d="M8 8.5h8M8 11.5h5" />
    </svg>
  );
}

function IconReceipt() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 3h12v18l-2.5-1.5L13 21l-1-1.5-1 1.5-2.5-1.5L6 21Z" />
      <path d="M9 8h6M9 11.5h6M9 15h3.5" />
    </svg>
  );
}

function IconDashboard() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.6" />
      <rect x="13" y="3.5" width="7.5" height="4.5" rx="1.6" />
      <rect x="13" y="10.5" width="7.5" height="10" rx="1.6" />
      <rect x="3.5" y="13.5" width="7.5" height="7" rx="1.6" />
    </svg>
  );
}

export default function HomePage() {
  return (
    <div className="landing">
      <header className="landing-header">
        <div className="landing-shell landing-header-inner">
          <Link href="/" className="landing-brand" aria-label="HoBS — home">
            <span className="landing-brand-mark" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 7.5 8 3l6 4.5" />
                <path d="M3.5 6.5V13h9V6.5" />
                <path d="M6.5 13V9.5h3V13" />
              </svg>
            </span>
            <span className="landing-brand-word">HoBS</span>
          </Link>
          <nav className="landing-nav" aria-label="Site">
            <Link href="/docs">Docs</Link>
            <Link href="/login" className="landing-nav-cta">
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="hero-orbs" aria-hidden="true">
            <span className="orb orb-gold" />
            <span className="orb orb-emerald" />
            <span className="orb orb-coral" />
          </div>
          <div className="hero-grain" aria-hidden="true" />

          <div className="landing-shell hero-inner">
            <div className="hero-copy">
              <span className="hero-eyebrow">
                <span className="hero-eyebrow-dot" />
                Hotel bookings, over WhatsApp
              </span>
              <h1 className="hero-title">
                Let guests book a room <em>the way they already message you.</em>
              </h1>
              <p className="hero-subtitle">
                HoBS answers guest chats on WhatsApp, checks room availability,
                takes payment, and drops the confirmed booking straight into
                your dashboard. No app for guests to download, no manual
                back-and-forth for you.
              </p>
              <div className="hero-actions">
                <Link href="/get-started" className="btn-glow">
                  Apply to onboard your hotel
                </Link>
                <Link href="/login" className="hero-link">
                  Already approved? Sign in
                </Link>
              </div>
            </div>

            <div className="hero-visual" aria-hidden="true">
              <svg className="flow-line" viewBox="0 0 400 190" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="flowGradient" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#34d399" />
                    <stop offset="55%" stopColor="#e7b24b" />
                    <stop offset="100%" stopColor="#ff7a59" />
                  </linearGradient>
                </defs>
                <path d="M200,0 L200,60 M200,60 C200,95 140,95 108,148 M200,60 C200,95 260,95 292,148" />
              </svg>

              <div className="chat-card">
                <div className="chat-card-label">
                  <span className="live-dot" />
                  Guest chat · WhatsApp
                </div>
                <div className="chat-thread">
                  <div className="chat-bubble guest">
                    Do you have a room for 2 nights from Fri?
                  </div>
                  <div className="chat-bubble hobs">
                    Yes — Standard Queen is open. ₦45,000/night. Pay now to
                    confirm?
                  </div>
                  <div className="chat-bubble guest">Yes please</div>
                  <div className="chat-bubble hobs">
                    Payment received ✅ Room 204 booked, Fri–Sun. See you then!
                  </div>
                </div>
              </div>

              <div className="flow-chips">
                <div className="flow-chip chip-emerald">
                  <span className="chip-dot" />
                  Room 204 · Booked
                </div>
                <div className="flow-chip chip-gold">
                  <span className="chip-dot" />
                  Synced to dashboard
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="landing-how">
          <div className="landing-shell">
            <h2 className="landing-h2">How it works</h2>
            <div className="how-flow">
              <div className="how-node">
                <div className="how-node-top">
                  <span className="how-icon icon-emerald">
                    <IconMessage />
                  </span>
                  <span className="how-index">01</span>
                </div>
                <p>A guest messages your WhatsApp number asking about a room.</p>
              </div>

              <div className="how-node">
                <div className="how-node-top">
                  <span className="how-icon icon-gold">
                    <IconReceipt />
                  </span>
                  <span className="how-index">02</span>
                </div>
                <p>
                  HoBS checks availability, quotes a price, and takes payment
                  right in the chat.
                </p>
              </div>

              <div className="how-node">
                <div className="how-node-top">
                  <span className="how-icon icon-coral">
                    <IconDashboard />
                  </span>
                  <span className="how-index">03</span>
                </div>
                <p>
                  You see the confirmed booking on your dashboard — nothing to
                  copy from chat to spreadsheet.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="landing-cta">
          <div className="landing-shell">
            <div className="cta-panel">
              <div>
                <h2>Ready to stop booking rooms by hand?</h2>
                <p>Applications are reviewed by our team, usually within 1–2 business days.</p>
              </div>
              <Link href="/get-started" className="btn-dark">
                Apply to onboard your hotel
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-shell landing-footer-inner">
          <span>© {new Date().getFullYear()} HoBS</span>
          <div className="landing-footer-links">
            <Link href="/docs">Docs</Link>
            <Link href="/terms">Terms</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
