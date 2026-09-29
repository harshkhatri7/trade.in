import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';

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

export default function RootLayout({ children }: { readonly children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a href="#main-content" className="skip-link">
          Skip to content
        </a>

        <header className="border-b border-line">
          <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-4 px-6 py-5">
            <span className="text-sm font-semibold tracking-[0.24em] uppercase">
              <Link href="/" className="hover:text-accent">
                HARSH&nbsp;QUANT&nbsp;OS
              </Link>
            </span>
            <nav
              aria-label="Primary"
              className="flex items-center gap-5 text-xs tracking-[0.16em] text-muted uppercase"
            >
              <Link href="/" className="hover:text-ink">
                Home
              </Link>
              <Link href="/datasets" className="hover:text-ink">
                Datasets
              </Link>
            </nav>
            <span className="rounded-full border border-line px-3 py-1 text-xs tracking-[0.16em] text-muted uppercase">
              Research workspace
            </span>
          </div>
        </header>

        <main id="main-content" className="mx-auto w-full max-w-5xl px-6 py-12 sm:py-16">
          {children}
        </main>

        <footer className="border-t border-line">
          <div className="mx-auto w-full max-w-5xl px-6 py-8 text-sm text-muted">
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
