import Link from "next/link";
import { SiteHeader } from "@/components/SiteHeader";
import { HeroMosaic } from "@/components/HeroMosaic";

export default function HomePage() {
  return (
    <>
      <SiteHeader />

      <HeroMosaic brand="HoBS" statement="Bookings, handled in the chat">
        <div className="hero-cta-row">
          <Link href="/get-started" className="btn">
            Apply to onboard your hotel
          </Link>
          <Link href="/login" className="text-link">
            Already approved? Sign in
          </Link>
        </div>
      </HeroMosaic>

      <main className="shell">
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
