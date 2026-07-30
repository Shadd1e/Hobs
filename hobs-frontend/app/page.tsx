import Link from "next/link";

export default function HomePage() {
  return (
    <main className="page">
      <h1>HoBS</h1>
      <p className="subtitle">
        Run your hotel&rsquo;s bookings from a simple WhatsApp chat. Guests
        message you, HoBS handles availability, confirmation, and payment.
      </p>

      <div className="btn-row">
        <Link href="/get-started" className="btn">
          Apply to onboard your hotel
        </Link>
      </div>

      <p className="helper-link">
        Already applied and approved?{" "}
        <Link href="/login">Sign in</Link>
      </p>
    </main>
  );
}
