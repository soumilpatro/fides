import Link from "next/link";
import type { ReactNode } from "react";
import { Screen } from "../ui";
import { Brand } from "../Brand";
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link href="/" aria-label="Fides foundation home">
          <Brand />
        </Link>
        <p className="micro">FRONTEND FOUNDATION</p>
        <nav aria-label="Foundation">
          <Link href="/" aria-current="page">
            Foundation preview <span aria-hidden="true">&#8599;</span>
          </Link>
        </nav>
        <div className="sidebar-footer">
          <span className="micro">ONE PRODUCT. TWO CLIENTS.</span>
          <p>
            A shared language.
            <br />A human foundation.
          </p>
          <small>F0 / App shell</small>
        </div>
      </aside>
      <Screen>{children}</Screen>
    </div>
  );
}
