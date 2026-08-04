"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { SiteHeader } from "@/components/SiteHeader";

// This page does no payment work itself — the Flutterwave webhook
// (backend) is what actually confirms the charge, updates the order/
// booking, and messages the guest on WhatsApp. This page only exists to
// catch the browser redirect Flutterwave sends the guest to right after
// they pay, so they don't land on a dead page, and to hand them straight
// back to the WhatsApp conversation where the real confirmation lives.
//
// Query params (appended server-side before the guest ever sees the
// Flutterwave link — see create_flutterwave_payment_link in
// checkout_service.py / booking_orchestrator.py):
//   ref — tx_ref / booking_code, shown to the guest as a receipt reference
//   wa  — the store/hotel's WhatsApp number to deep-link back into

function buildWhatsAppLink(wa: string, ref: string | null) {
  const digits = wa.replace(/[^\d]/g, "");
  const text = ref
    ? `Hi! I just completed payment (ref: ${ref}).`
    : "Hi! I just completed payment.";
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

export default function PaymentSuccessPage() {
  return (
    <Suspense fallback={null}>
      <PaymentSuccessContent />
    </Suspense>
  );
}

function PaymentSuccessContent() {
  const params = useSearchParams();
  const ref = params.get("ref");
  const wa = params.get("wa");

  const waLink = useMemo(() => (wa ? buildWhatsAppLink(wa, ref) : null), [wa, ref]);
  const [attempted, setAttempted] = useState(false);

  // Auto-open WhatsApp once. Mobile browsers generally still honor a
  // location change triggered on initial render/tap-through from another
  // app (the Flutterwave redirect), even without a fresh user gesture on
  // this page — but we don't rely on it working: the button below is the
  // real fallback for browsers that block it.
  useEffect(() => {
    if (waLink && !attempted) {
      setAttempted(true);
      window.location.href = waLink;
    }
  }, [waLink, attempted]);

  return (
    <>
      <SiteHeader />
      <main className="shell" style={{ maxWidth: 560, paddingTop: 64, paddingBottom: 64 }}>
        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: "var(--radius)",
            padding: 32,
            textAlign: "center",
            background: "var(--paper)",
          }}
        >
          <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
          <h1 style={{ marginBottom: 8 }}>Payment received</h1>
          <p className="subtitle" style={{ marginBottom: 4 }}>
            Your confirmation is on its way in WhatsApp.
          </p>
          {ref && (
            <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 24 }}>
              Reference: {ref}
            </p>
          )}

          {waLink ? (
            <a href={waLink} className="btn" style={{ display: "inline-block" }}>
              Open WhatsApp
            </a>
          ) : (
            <p style={{ color: "var(--muted)", fontSize: 14 }}>
              You can close this tab and return to your WhatsApp chat to see your
              confirmation.
            </p>
          )}

          <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 20 }}>
            Didn&apos;t get redirected automatically? Tap the button above.
          </p>
        </div>
      </main>
    </>
  );
}
