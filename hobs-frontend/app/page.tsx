"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

const PHRASES = [
  "Your hotel's smartest receptionist lives inside WhatsApp.",
  "Every missed reply is another booking walking into another hotel.",
  "Hotels rarely lose bookings because they're full — they lose them because they replied too late.",
  "HoBS replies in seconds. Day, night, and everything after.",
  "A guest messages. You do nothing else.",
];

function IconSparkle() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0c.4 2.9 1 4.6 1.8 5.4C10.6 6.2 12.3 6.8 15 7c-2.7.2-4.4.8-5.2 1.6C9 9.4 8.4 11.1 8 14c-.4-2.9-1-4.6-1.8-5.4C5.4 7.8 3.7 7.2 1 7c2.7-.2 4.4-.8 5.2-1.6C7 4.6 7.6 2.9 8 0Z" />
    </svg>
  );
}

function IconClose() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M3 3l10 10M13 3 3 13" />
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

/**
 * Types the given phrases out one character at a time, pauses, deletes, and
 * moves to the next phrase — looping forever. Falls back to a plain,
 * un-jittery crossfade for anyone with prefers-reduced-motion set.
 */
type TypewriterOptions = {
  typingSpeed?: number;
  deletingSpeed?: number;
  pause?: number;
};

function useTypewriter(
  phrases: string[],
  { typingSpeed = 42, deletingSpeed = 24, pause = 1900 }: TypewriterOptions = {}
) {
  const [index, setIndex] = useState(0);
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<"typing" | "deleting">("typing");
  const reducedMotionRef = useRef(false);

  useEffect(() => {
    reducedMotionRef.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotionRef.current) {
      setText(phrases[0] ?? "");
    }
  }, [phrases]);

  useEffect(() => {
    if (reducedMotionRef.current) {
      const interval = setInterval(() => {
        setIndex((i) => (i + 1) % phrases.length);
      }, 3400);
      return () => clearInterval(interval);
    }

    const current = phrases[index % phrases.length] ?? "";
    let timeout: ReturnType<typeof setTimeout>;

    if (phase === "typing") {
      if (text.length < current.length) {
        timeout = setTimeout(() => setText(current.slice(0, text.length + 1)), typingSpeed);
      } else {
        timeout = setTimeout(() => setPhase("deleting"), pause);
      }
    } else {
      if (text.length > 0) {
        timeout = setTimeout(() => setText(current.slice(0, text.length - 1)), deletingSpeed);
      } else {
        setPhase("typing");
        setIndex((i) => (i + 1) % phrases.length);
      }
    }

    return () => clearTimeout(timeout);
  }, [text, phase, index, phrases, typingSpeed, deletingSpeed, pause]);

  useEffect(() => {
    if (reducedMotionRef.current) setText(phrases[index] ?? "");
  }, [index, phrases]);

  return text;
}

type GetStartedModalProps = {
  open: boolean;
  onClose: () => void;
};

function GetStartedModal({ open, onClose }: GetStartedModalProps) {
  const [form, setForm] = useState({ hotel: "", whatsapp: "", email: "" });
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    // No backend wired up yet — swap this for a real submit (API route,
    // WhatsApp webhook, form service, etc.) when you're ready to go live.
    setSubmitted(true);
  };

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      onClick={onClose}
    >
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">
          <IconClose />
        </button>

        {!submitted ? (
          <>
            <span className="modal-eyebrow">Start for ₦0 today</span>
            <h2 id="modal-title" className="modal-title">
              Tell us about your hotel
            </h2>
            <p className="modal-sub">No setup fee. We review applications within 1–2 business days.</p>

            <form className="modal-form" onSubmit={handleSubmit}>
              <label>
                Hotel name
                <input
                  required
                  type="text"
                  value={form.hotel}
                  onChange={(e) => setForm({ ...form, hotel: e.target.value })}
                  placeholder="e.g. Lagoon View Hotel"
                />
              </label>
              <label>
                WhatsApp number
                <input
                  required
                  type="tel"
                  value={form.whatsapp}
                  onChange={(e) => setForm({ ...form, whatsapp: e.target.value })}
                  placeholder="+234 800 000 0000"
                />
              </label>
              <label>
                Email (optional)
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="you@hotel.com"
                />
              </label>
              <button type="submit" className="btn-gold modal-submit">
                Submit application
              </button>
            </form>
          </>
        ) : (
          <div className="modal-success">
            <span className="modal-success-icon">
              <IconCheck />
            </span>
            <h2 className="modal-title">Application received</h2>
            <p className="modal-sub">
              We&rsquo;ll reach out on WhatsApp within 1–2 business days to get{" "}
              {form.hotel || "your hotel"} set up.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function HomePage() {
  const [modalOpen, setModalOpen] = useState(false);
  const typed = useTypewriter(PHRASES);

  useEffect(() => {
    document.body.style.overflow = modalOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [modalOpen]);

  return (
    <div className="landing landing-single">
      <div className="landing-bg" aria-hidden="true">
        <div className="bg-grid" />
        <span className="aurora-blob aurora-blob-a" />
        <span className="aurora-blob aurora-blob-b" />
        <span className="aurora-blob aurora-blob-c" />
        <div className="bg-vignette" />
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
            <Link href="/login" className="landing-nav-signin">
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main className="hero-single">
        <div className="landing-shell">
          <div className="hero-single-inner">
            <span className="hero-kicker">
              <IconSparkle />
              Hotel bookings, over WhatsApp
            </span>

            <h1 className="type-headline">
              <span className="sr-only">{PHRASES.join(" ")}</span>
              <span aria-hidden="true" className="type-headline-text">
                {typed}
                <span className="type-cursor" />
              </span>
            </h1>

            <div className="hero-single-actions">
              <button className="btn-gold" onClick={() => setModalOpen(true)}>
                Start for ₦0 today
              </button>
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

      <GetStartedModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  );
}
