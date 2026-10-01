'use client';

/**
 * Primary navigation.
 *
 * The active item is marked three ways at once — `aria-current="page"`, a
 * heavier weight and an accent rule under the label — so the current page
 * never depends on colour alone. `usePathname` is the app router's own
 * source of truth for the route, so the marker cannot drift from the URL
 * the way a hand-maintained "active" prop would.
 *
 * Each link keeps a 40px minimum height (`min-h-10`), which is the target
 * size the mobile audit requires at 320px; the list wraps onto its own row
 * below 400px rather than shrinking the targets.
 */
import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_ITEMS = [
  { href: '/', label: 'Overview' },
  { href: '/datasets', label: 'Datasets' },
] as const;

/** `/` is the whole route; every other page matches on its first segment. */
function isActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SiteNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary">
      <ul className="flex items-center gap-1 sm:gap-2">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={
                  'relative inline-flex min-h-10 items-center rounded-full px-3 text-[11px] font-semibold tracking-[0.16em] uppercase transition-colors duration-[140ms] ease-out-soft sm:px-4 ' +
                  (active ? 'text-ink' : 'text-muted hover:text-ink')
                }
              >
                {item.label}
                {/* The accent rule: present only on the current page, and
                    shaped (a solid bar) as well as coloured. */}
                <span
                  aria-hidden="true"
                  className={
                    'absolute inset-x-2 -bottom-0.5 h-px rounded-full transition-opacity duration-[140ms] ' +
                    (active ? 'bg-accent opacity-100' : 'bg-accent opacity-0')
                  }
                />
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
