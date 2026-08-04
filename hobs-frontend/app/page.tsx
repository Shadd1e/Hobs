import Link from "next/link";

function IconSparkle() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0c.4 2.9 1 4.6 1.8 5.4C10.6 6.2 12.3 6.8 15 7c-2.7.2-4.4.8-5.2 1.6C9 9.4 8.4 11.1 8 14c-.4-2.9-1-4.6-1.8-5.4C5.4 7.8 3.7 7.2 1 7c2.7-.2 4.4-.8 5.2-1.6C7 4.6 7.6 2.9 8 0Z" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8.5 6.2 12 13 4" />
    </svg>
  );
}

function IconArrow() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 8h11M9 4l4 4-4 4" />
    </svg>
  );
}

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
      <div className="landing-aurora" aria-hidden="true">
        <span className="aurora-blob aurora-blob-a" />
        <span className="aurora-blob aurora-blob-b" />
        <span className="aurora-blob aurora-blob-c" />
        <span className="aurora-blob aurora-blob-d" />
      </div>

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
            <Link href="/login">Sign in</Link>
          </nav>
        </div>
      </header>

      <main>
        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <section className="landing-hero">
          <div className="landing-shell">
          <div className="hero-grid">
            <div className="hero-copy">
              <span className="hero-kicker">
                <IconSparkle />
                Hotel bookings, over WhatsApp
              </span>

              <h1 className="hero-title">
                Your hotel&rsquo;s smartest receptionist lives inside{" "}
                <span className="gold-text">WhatsApp</span>.
              </h1>

              <p className="hero-loss">
                Every missed reply is <strong>another booking walking into another hotel.</strong>{" "}
                HoBS answers instantly, takes payment, and confirms the room — before the guest
                thinks to message anyone else.
              </p>

              <div className="hero-actions">
                <Link href="/get-started" className="btn-gold">
                  Start for ₦0 today
                </Link>
                <Link href="/login" className="hero-link">
                  Already approved? Sign in
                </Link>
              </div>
              <p className="hero-microcopy">
                No setup fee. Applications are reviewed within 1–2 business days.
              </p>
            </div>

            <div className="hero-visual" aria-hidden="true">
              <div className="glass-panel chat-panel">
                <div className="panel-label">
                  <span className="live-dot" />
                  Guest chat · WhatsApp
                </div>
                <div className="chat-thread">
                  <div className="chat-bubble guest" style={{ animationDelay: "0.1s" }}>
                    Do you have a room for 2 nights from Fri?
                  </div>
                  <div className="reply-slot">
                    <div className="chat-bubble typing">
                      <span />
                      <span />
                      <span />
                    </div>
                    <div className="chat-bubble hobs" style={{ animationDelay: "1.3s" }}>
                      Yes — Standard Queen is open. <span className="gold-text">₦45,000/night.</span>{" "}
                      Pay now to confirm?
                    </div>
                  </div>
                  <div className="chat-bubble guest" style={{ animationDelay: "1.7s" }}>
                    Yes please
                  </div>
                  <div className="chat-bubble hobs success" style={{ animationDelay: "2.1s" }}>
                    Payment received ✅ Room 204 booked, Fri–Sun. See you then!
                  </div>
                </div>
              </div>

              <div className="hero-connector">
                <span className="connector-badge">
                  <IconArrow />
                </span>
              </div>

              <div className="glass-panel summary-panel">
                <div className="panel-label">
                  <span className="live-dot" />
                  Dashboard · Booking summary
                </div>
                <div className="summary-rows">
                  <div className="summary-row" style={{ animationDelay: "2.3s" }}>
                    <span className="summary-check">
                      <IconCheck />
                    </span>
                    <span className="summary-text">
                      Payment received · <span className="value">₦45,000</span>
                    </span>
                  </div>
                  <div className="summary-row" style={{ animationDelay: "2.55s" }}>
                    <span className="summary-check">
                      <IconCheck />
                    </span>
                    <span className="summary-text">Room 204 assigned · Fri–Sun</span>
                  </div>
                  <div className="summary-row" style={{ animationDelay: "2.8s" }}>
                    <span className="summary-check">
                      <IconCheck />
                    </span>
                    <span className="summary-text">Dashboard updated</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          </div>
        </section>

        {/* ── Urgency: sell the loss ──────────────────────────────────── */}
        <section className="landing-urgent">
          <div className="landing-shell urgent-inner">
            <p className="urgent-kicker">Right now, somewhere, a guest is messaging your hotel</p>
            <ul className="urgent-list">
              <li>While you&rsquo;re asleep.</li>
              <li>While you&rsquo;re driving.</li>
              <li>While you&rsquo;re serving another guest.</li>
              <li>While your front desk is busy with someone else.</li>
            </ul>
            <p className="urgent-beat">
              If nobody replies in the next few minutes, they won&rsquo;t wait. They&rsquo;ll message
              the next hotel on their list.
            </p>
            <p className="urgent-punch gold-text">HoBS makes sure that never happens.</p>
          </div>
        </section>

        {/* ── How it works ────────────────────────────────────────────── */}
        <section className="landing-how">
          <div className="landing-shell">
            <div className="how-head">
              <span className="how-eyebrow">The process</span>
              <h2 className="landing-h2">A guest messages. You do nothing else.</h2>
            </div>
            <div className="how-flow">
              <div className="how-node">
                <div className="how-node-top">
                  <span className="how-icon">
                    <IconMessage />
                  </span>
                  <span className="how-index">01</span>
                </div>
                <p>A guest messages your WhatsApp number asking about a room.</p>
              </div>

              <div className="how-node">
                <div className="how-node-top">
                  <span className="how-icon">
                    <IconReceipt />
                  </span>
                  <span className="how-index">02</span>
                </div>
                <p>HoBS checks availability, quotes a price, and takes payment right in the chat.</p>
              </div>

              <div className="how-node">
                <div className="how-node-top">
                  <span className="how-icon">
                    <IconDashboard />
                  </span>
                  <span className="how-index">03</span>
                </div>
                <p>
                  You see the confirmed booking on your dashboard — nothing to copy from chat to
                  spreadsheet.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── Reframe ──────────────────────────────────────────────────── */}
        <section className="landing-quote">
          <div className="landing-shell">
          <div className="quote-inner">
            <span className="quote-mark" aria-hidden="true">&ldquo;</span>
            <p className="quote-text">
              Hotels rarely lose bookings because they&rsquo;re full. They lose them because they
              replied <span className="gold-text">too late.</span>
            </p>
            <p className="quote-sub">HoBS replies in seconds, every time — day, night, and everything after.</p>
          </div>
          </div>
        </section>

        {/* ── CTA ──────────────────────────────────────────────────────── */}
        <section className="landing-cta">
          <div className="landing-shell">
            <div className="cta-panel">
              <div>
                <h2>Every conversation is an opportunity.</h2>
                <p>
                  Let HoBS handle the chat while your team looks after the guests already through
                  your doors.
                </p>
              </div>
              <Link href="/get-started" className="btn-dark">
                <span className="btn-dark-label">Start for ₦0 today</span>
                <span className="btn-dark-sub">Setup is free. We only get paid when you do.</span>
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
