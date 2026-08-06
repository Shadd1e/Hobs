"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type CSSProperties } from "react";

const PHRASES = [
  "Your hotel's smartest receptionist lives inside WhatsApp.",
  "Every missed reply is another booking walking into another hotel.",
  "Hotels rarely lose bookings because they're full — they lose them because they replied too late.",
  "HoBS replies in seconds. Day, night, and everything after.",
  "A guest messages. You do nothing else.",
];

// Deterministic PRNG (mulberry32) so the background grid renders identically
// on the server and on the client — a plain Math.random() here would cause
// a hydration mismatch since this component's first render happens on both.
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const BOOKING_CELL_COUNT = 320;

type BookingCell = {
  id: number;
  live: boolean;
  delay: number;
  duration: number;
};

function buildBookingCells(): BookingCell[] {
  const rand = mulberry32(1337);
  return Array.from({ length: BOOKING_CELL_COUNT }, (_, id) => {
    const live = rand() < 0.14;
    return {
      id,
      live,
      delay: Math.round(rand() * 600) / 100,
      duration: Math.round((2.6 + rand() * 1.8) * 100) / 100,
    };
  });
}

/**
 * Types the given phrases out one character at a time, pauses on the full
 * phrase, deletes it, then moves to the next — looping forever. Speed
 * jitters slightly per character and slows after punctuation so it reads
 * like an actual person typing rather than a metronome.
 */
type TypewriterOptions = {
  typingSpeed?: number;
  deletingSpeed?: number;
  pause?: number;
};

function useTypewriter(
  phrases: string[],
  { typingSpeed = 22, deletingSpeed = 12, pause = 1500 }: TypewriterOptions = {}
) {
  const [index, setIndex] = useState(0);
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<"typing" | "holding" | "deleting" | "waiting">("typing");

  useEffect(() => {
    const current = phrases[index % phrases.length] ?? "";
    let timeout: ReturnType<typeof setTimeout>;

    if (phase === "typing") {
      if (text.length < current.length) {
        const lastChar = current[text.length - 1] ?? "";
        const nextChar = current[text.length] ?? "";
        let delay = typingSpeed + Math.random() * 24;
        if (nextChar === " ") delay *= 0.5;
        if (".,!?—".includes(lastChar)) delay += 140;
        timeout = setTimeout(() => setText(current.slice(0, text.length + 1)), delay);
      } else {
        timeout = setTimeout(() => setPhase("holding"), pause);
      }
    } else if (phase === "holding") {
      setPhase("deleting");
    } else if (phase === "deleting") {
      if (text.length > 0) {
        timeout = setTimeout(() => setText(current.slice(0, text.length - 1)), deletingSpeed);
      } else {
        timeout = setTimeout(() => setPhase("waiting"), 200);
      }
    } else {
      setPhase("typing");
      setIndex((i) => (i + 1) % phrases.length);
    }

    return () => clearTimeout(timeout);
  }, [text, phase, index, phrases, typingSpeed, deletingSpeed, pause]);

  return text;
}

export default function HomePage() {
  const typed = useTypewriter(PHRASES);
  const cells = useMemo(buildBookingCells, []);

  return (
    <div className="landing landing-single">
      <div className="landing-bg" aria-hidden="true">
        <div className="booking-grid">
          {cells.map((cell) => (
            <span
              key={cell.id}
              className={`booking-cell${cell.live ? " is-live" : ""}`}
              style={
                cell.live
                  ? ({
                      "--delay": `${cell.delay}s`,
                      "--dur": `${cell.duration}s`,
                    } as CSSProperties)
                  : undefined
              }
            />
          ))}
        </div>
      </div>

      <header className="landing-header">
        <div className="landing-shell landing-header-inner">
          <Link href="/" className="landing-brand" aria-label="The HoBS — home">
            <span className="landing-brand-mark" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 7.5 8 3l6 4.5" />
                <path d="M3.5 6.5V13h9V6.5" />
                <path d="M6.5 13V9.5h3V13" />
              </svg>
            </span>
            <span className="landing-brand-word">
              The HoBS
              <span className="landing-brand-sub">Powered by Altekflo</span>
            </span>
          </Link>
          <nav className="landing-nav" aria-label="Site">
            <Link href="/docs">Docs</Link>
            <Link href="/login" className="landing-nav-signin">
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main className="hero-single">
        <div className="landing-shell">
          <div className="hero-single-inner">
            <h1 className="hero-lead">
              You&rsquo;re here. Now you can accept{" "}
              <span className="gold-text">BOOKINGS/RESERVATIONS</span> over a WhatsApp DM.
            </h1>

            <p className="type-headline">
              <span className="sr-only">{PHRASES.join(" ")}</span>
              <span aria-hidden="true" className="type-headline-text">
                {typed}
                <span className="type-cursor" />
              </span>
            </p>

            <div className="hero-single-actions">
              <Link href="/get-started" className="btn-gold">
                Start for ₦0 today
              </Link>
              <p className="hero-microcopy">No setup fee. Applications reviewed within 1–2 business days.</p>
            </div>
          </div>
        </div>
      </main>

      <footer className="landing-footer-single">
        <div className="landing-shell landing-footer-single-inner">
          <span>© {new Date().getFullYear()} HoBS</span>
          <Link href="/terms">Terms</Link>
        </div>
      </footer>
    </div>
  );
}
