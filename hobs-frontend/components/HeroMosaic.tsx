import type { ReactNode } from "react";

/** Reusable line-art icon sprite for the hero mosaic tiles. Rendered once,
 * referenced everywhere via <use> so the marquee stays cheap to animate. */
export function TileIconDefs() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <defs>
        <g id="icon-bed" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <rect x="6" y="20" width="36" height="16" rx="2" />
          <path d="M6 28h36" />
          <path d="M9 20v-4a3 3 0 0 1 3-3h24a3 3 0 0 1 3 3v4" />
          <rect x="11" y="15" width="9" height="6" rx="1.5" />
          <rect x="22" y="15" width="9" height="6" rx="1.5" />
          <path d="M6 36v4M42 36v4" />
        </g>

        <g id="icon-keycard" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="10" width="30" height="28" rx="3" />
          <rect x="14" y="16" width="8" height="6" rx="1" />
          <path d="M14 28h20M14 32h12" />
        </g>

        <g id="icon-palm" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M24 40V22" />
          <path d="M24 22c-4-6-12-6-15-2 5 2 9 1 15 2Z" />
          <path d="M24 22c4-6 12-6 15-2-5 2-9 1-15 2Z" />
          <path d="M24 22c-2-7 1-12 1-12s5 4 3 12Z" />
        </g>

        <g id="icon-moon" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M29 10a13 13 0 1 0 9 20 10 10 0 0 1-9-20Z" />
          <path d="M38 12v4M36 14h4" />
        </g>

        <g id="icon-lounger" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 30h14l14-10" />
          <path d="M6 30v6M20 30v6M34 20l6 2" />
          <circle cx="40" cy="24" r="2" />
          <path d="M6 36h28" />
        </g>

        <g id="icon-cloche" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8 30a16 8 0 0 1 32 0" />
          <path d="M6 30h36" />
          <path d="M24 14v4" />
          <circle cx="24" cy="12" r="1.6" />
        </g>

        <g id="icon-luggage" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <rect x="10" y="16" width="28" height="20" rx="3" />
          <path d="M18 16v-3a3 3 0 0 1 3-3h6a3 3 0 0 1 3 3v3" />
          <path d="M10 24h28M18 24v12M30 24v12" />
        </g>

        <g id="icon-balcony" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 18h36" />
          <path d="M10 18v18M16 18v18M22 18v18M28 18v18M34 18v18M40 18v18" />
          <path d="M12 12l4 6M12 12v6" />
        </g>

        <g id="icon-umbrella" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M24 10c9 0 15 6 15 10H9c0-4 6-10 15-10Z" />
          <path d="M24 20v16" />
          <path d="M24 36c0 2-2 3-4 3" />
          <rect x="15" y="30" width="18" height="4" rx="1" />
        </g>

        <g id="icon-facade" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <rect x="10" y="8" width="28" height="32" rx="2" />
          <path d="M20 40v-8a4 4 0 0 1 8 0v8" />
          <path d="M15 14h4M15 21h4M15 28h4M29 14h4M29 21h4M29 28h4" />
        </g>

        <g id="icon-glasses" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 10l6 10-6 8" />
          <path d="M6 10h12M12 28v8M8 36h8" />
          <path d="M36 10l6 10-6 8" />
          <path d="M30 10h12M36 28v8M32 36h8" />
        </g>

        <g id="icon-doorhang" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="24" cy="10" r="3" />
          <path d="M20 13l-6 10a4 4 0 0 0 4 6h12a4 4 0 0 0 4-6l-6-10" />
          <path d="M18 27h12" />
        </g>

        <g id="icon-tag" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 10l16 0 14 14-16 16-14-14Z" />
          <circle cx="16" cy="16" r="2" />
        </g>

        <g id="icon-bath" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 26h36v3a9 9 0 0 1-9 9H15a9 9 0 0 1-9-9v-3Z" />
          <path d="M10 26v-9a4 4 0 0 1 4-4" />
          <path d="M30 14v4M34 16h-4" />
          <path d="M11 38v3M35 38v3" />
        </g>
      </defs>
    </svg>
  );
}

export const TILES: { icon: string; label: string; variant: "dark" | "light" }[] = [
  { icon: "icon-bed", label: "Suites", variant: "dark" },
  { icon: "icon-keycard", label: "Check-in", variant: "light" },
  { icon: "icon-palm", label: "Garden View", variant: "dark" },
  { icon: "icon-moon", label: "Late Checkout", variant: "dark" },
  { icon: "icon-lounger", label: "Poolside", variant: "light" },
  { icon: "icon-cloche", label: "Room Service", variant: "dark" },
  { icon: "icon-luggage", label: "Fresh Linen", variant: "dark" },
  { icon: "icon-balcony", label: "Rooftop", variant: "light" },
  { icon: "icon-umbrella", label: "Ocean View", variant: "dark" },
  { icon: "icon-facade", label: "Concierge", variant: "dark" },
  { icon: "icon-glasses", label: "Twin Room", variant: "light" },
  { icon: "icon-doorhang", label: "Do Not Disturb", variant: "dark" },
  { icon: "icon-tag", label: "Best Rate", variant: "dark" },
  { icon: "icon-bath", label: "En Suite", variant: "light" },
];

function MosaicRow({ offset, reverse, duration }: { offset: number; reverse?: boolean; duration: number }) {
  const seq = [...TILES.slice(offset), ...TILES.slice(0, offset)];
  const doubled = [...seq, ...seq];
  return (
    <div
      className={`mosaic-row${reverse ? " reverse" : ""}`}
      style={{ animationDuration: `${duration}s` }}
    >
      {doubled.map((t, i) => (
        <div className={`tile ${t.variant}`} key={i}>
          <svg viewBox="0 0 48 48">
            <use href={`#${t.icon}`} />
          </svg>
          <span>{t.label}</span>
        </div>
      ))}
    </div>
  );
}

export function HeroMosaic({
  brand,
  statement,
  children,
}: {
  brand: string;
  statement: string;
  children: ReactNode;
}) {
  return (
    <section className="mosaic-hero">
      <TileIconDefs />
      <div className="mosaic-rows-wrap" aria-hidden="true">
        <MosaicRow offset={0} duration={46} />
        <MosaicRow offset={5} duration={60} reverse />
        <MosaicRow offset={9} duration={52} />
      </div>
      <div className="hero-scrim" />
      <span className="edge-label left">Rooms · Rates · Guests · Stays</span>
      <span className="edge-label right">WhatsApp · Payments · Dashboard</span>
      <div className="hero-center">
        <span className="brand-word-lg">{brand}</span>
        <h1 className="statement">{statement}</h1>
        {children}
      </div>
    </section>
  );
}
