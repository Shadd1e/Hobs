import Link from "next/link";
import { SiteHeader } from "@/components/SiteHeader";

export default function HomePage() {
  return (
    <>
      <SiteHeader />

      <main className="shell">
        <section className="hero">
          <div className="hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">Hotel bookings, over WhatsApp</p>
              <h1>Let guests book a room the way they already message you.</h1>
              <p className="subtitle">
                HoBS answers guest chats on WhatsApp, checks room availability,
                takes payment, and drops the confirmed booking straight into
                your dashboard. No app for guests to download, no manual
                back-and-forth for you.
              </p>
              <div className="hero-cta-row">
                <Link href="/get-started" className="btn">
                  Apply to onboard your hotel
                </Link>
                <Link href="/login" className="text-link">
                  Already approved? Sign in
                </Link>
              </div>
            </div>

            <div className="ticket" aria-hidden="true">
              <div className="ticket-label">Guest chat · WhatsApp</div>
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
              <div className="ticket-foot">BOOKING CONFIRMED · NO APP NEEDED</div>
            </div>
          </div>
        </section>

        <section className="how-it-works">
          <h2>How it works</h2>
          <div className="how-grid">
            <div className="how-step">
              <span className="how-step-num">01</span>
              <p>A guest messages your WhatsApp number asking about a room.</p>
            </div>
            <div className="how-step">
              <span className="how-step-num">02</span>
              <p>
                HoBS checks availability, quotes a price, and takes payment
                right in the chat.
              </p>
            </div>
            <div className="how-step">
              <span className="how-step-num">03</span>
              <p>
                You see the confirmed booking on your dashboard — nothing to
                copy from chat to spreadsheet.
              </p>
            </div>
          </div>
        </section>

        <section style={{ paddingBottom: 72 }}>
          <div className="cta-band">
            <div>
              <h2>Ready to stop booking rooms by hand?</h2>
              <p>Applications are reviewed by our team, usually within 1–2 business days.</p>
            </div>
            <Link href="/get-started" className="btn">
              Apply to onboard your hotel
            </Link>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <span>© {new Date().getFullYear()} HoBS</span>
        <div className="site-footer-links">
          <Link href="/docs">Docs</Link>
          <Link href="/terms">Terms</Link>
        </div>
      </footer>
    </>
  );
}
