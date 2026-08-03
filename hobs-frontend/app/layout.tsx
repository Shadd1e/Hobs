import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Fraunces, Inter } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import { StaffAuthProvider } from "@/lib/staffAuth";
import "./globals.css";

const display = Fraunces({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

const body = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HoBS — Hotel Booking System",
  description:
    "Run your hotel's bookings from a simple WhatsApp chat. Guests message you, HoBS handles availability, confirmation, and payment.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body>
        <AuthProvider>
          <StaffAuthProvider>{children}</StaffAuthProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
