import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'HARSH QUANT OS',
  description:
    'Private quantitative trading research platform - foundation stage. Research and analysis only; live trading is not implemented.',
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
          <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-6 py-5">
            <span className="text-sm font-semibold tracking-[0.24em] uppercase">
              HARSH&nbsp;QUANT&nbsp;OS
            </span>
            <span className="rounded-full border border-line px-3 py-1 text-xs tracking-[0.16em] text-muted uppercase">
              Foundation
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
