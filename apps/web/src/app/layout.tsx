import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';

import { SiteNav } from '../components/site-nav';

import './globals.css';

export const metadata: Metadata = {
  title: 'HARSH QUANT OS',
  description:
    'Private quantitative trading research platform - research and analysis only; live trading is not implemented.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#0a0c10',
};

/**
 * The shell: ambient layer, skip link, sticky glass header, main column and
 * the honest footer. The navigation itself lives in `components/site-nav`
 * because marking the current page needs the router, i.e. a client
 * component — this file stays a server component so `metadata` keeps
 * working.
 */
export default function RootLayout({ children }: { readonly children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        {/* Ambient light layer, referenced by `.ambient` in globals.css. */}
        <div className="ambient" aria-hidden="true" />

        <a href="#main-content" className="skip-link">
          Skip to content
        </a>

        {/* Level-3 glass: the one continuously blurred surface, so the bar
            stays legible over content scrolling beneath it. */}
        <header className="glass-3 sticky top-0 z-40">
          <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 py-3 sm:px-6 sm:py-4">
            <Link
              href="/"
              className="inline-flex min-h-10 items-center gap-2 text-sm font-semibold tracking-[0.2em] text-ink uppercase"
            >
              <span
                aria-hidden="true"
                className="inline-block size-2 rounded-full bg-accent shadow-[0_0_12px_var(--color-accent)]"
              />
              HARSH&nbsp;QUANT&nbsp;OS
            </Link>

            <div className="order-3 flex w-full items-center justify-between gap-3 border-t border-white/5 pt-2 sm:order-none sm:w-auto sm:border-t-0 sm:pt-0">
              <SiteNav />
              <span className="hidden rounded-full border border-white/10 bg-black/25 px-3 py-1 text-[10px] tracking-[0.16em] text-muted uppercase sm:inline-block">
                Research workspace
              </span>
            </div>
          </div>
        </header>

        <main id="main-content" className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 sm:py-16">
          {children}
        </main>

        <footer className="border-t border-white/5 bg-black/20">
          <div className="mx-auto w-full max-w-5xl px-4 py-8 text-sm text-muted sm:px-6">
            <p>
              Research infrastructure in development. Live trading:{' '}
              <strong className="text-ink">disabled</strong> · Broker:{' '}
              <strong className="text-ink">not connected</strong> · Paper trading:{' '}
              <strong className="text-ink">not implemented</strong>.
            </p>
            <p className="mt-2">
              Nothing here is a claim about returns. Backtests describe the past, not the future.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
