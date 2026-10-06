import type { ReactNode } from 'react'

interface CardProps {
  id?: string
  icon?: ReactNode
  title: string
  /** One plain-language line under the title. */
  summary?: ReactNode
  /** Methodology, data provenance and limits — collapsed by default. */
  howItWorks?: ReactNode
  /** Extra controls shown on the right of the header (selects, toggles). */
  actions?: ReactNode
  className?: string
  children: ReactNode
}

/**
 * Shared dashboard card. Keeps every panel's honest methodology/limits text
 * one click away ("How this works") instead of in front of every reader.
 */
export function Card({ id, icon, title, summary, howItWorks, actions, className, children }: CardProps) {
  return (
    <section id={id} className={`card${className ? ` ${className}` : ''}`} aria-labelledby={id ? `${id}-title` : undefined}>
      <header className="card-head">
        <div className="card-titles">
          <h2 id={id ? `${id}-title` : undefined} className="card-title">
            {icon}
            {title}
          </h2>
          {summary && <p className="card-summary">{summary}</p>}
        </div>
        {actions && <div className="card-actions">{actions}</div>}
      </header>
      <div className="card-body">{children}</div>
      {howItWorks && (
        <details className="how-it-works">
          <summary>How this works</summary>
          <div className="how-it-works-body">{howItWorks}</div>
        </details>
      )}
    </section>
  )
}
