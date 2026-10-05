/**
 * Small hand-rolled inline-SVG icon set for the visual-polish pass — no new
 * npm dependency, just a handful of simple line-style glyphs used in the
 * hero logomark, the nav tabs, and the Authority dashboard's section
 * headers/stat cards.
 *
 * Every icon renders `aria-hidden="true"` and `focusable="false"` with no
 * `<title>` or text node, so it never changes an element's accessible name
 * or `textContent` — CitizenView.test.tsx asserts on exact visible text via
 * getByText, and these icons must never be able to affect that.
 */
import type { SVGProps } from 'react'

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height'> {
  size?: number
}

function Base({ size = 18, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

/** The Girivarsha logomark — a stylised raindrop over a mountain ridge. */
export function IconLogomark(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3 17 L9 8 L13 13 L17 6 L21 17 Z" />
      <path d="M12 2.5 C12 2.5 9 6.5 9 9 a3 3 0 0 0 6 0 c0-2.5-3-6.5-3-6.5Z" />
    </Base>
  )
}

export function IconHome(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 11.5 L12 4 L20 11.5" />
      <path d="M6 10 V20 H18 V10" />
    </Base>
  )
}

export function IconShield(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3 L19 6 V11 C19 16 16 19.5 12 21 C8 19.5 5 16 5 11 V6 Z" />
    </Base>
  )
}

export function IconMap(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M9 4 L4 6 V20 L9 18 L15 20 L20 18 V4 L15 6 L9 4 Z" />
      <path d="M9 4 V18" />
      <path d="M15 6 V20" />
    </Base>
  )
}

export function IconLayers(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3 L21 8 L12 13 L3 8 Z" />
      <path d="M3 12.5 L12 17.5 L21 12.5" />
      <path d="M3 16.5 L12 21.5 L21 16.5" />
    </Base>
  )
}

export function IconGauge(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 15 a8 8 0 1 1 16 0" />
      <path d="M12 15 L16 10" />
      <path d="M12 15 h.01" />
    </Base>
  )
}

export function IconMessage(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 5 H20 V16 H9 L5 19.5 V16 H4 Z" />
    </Base>
  )
}

export function IconRadio(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="2.4" />
      <path d="M8.5 8.5 a5 5 0 0 0 0 7" />
      <path d="M15.5 8.5 a5 5 0 0 1 0 7" />
      <path d="M5.5 5.5 a9.5 9.5 0 0 0 0 13" />
      <path d="M18.5 5.5 a9.5 9.5 0 0 1 0 13" />
    </Base>
  )
}

export function IconRoute(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="5.5" cy="18.5" r="2" />
      <circle cx="18.5" cy="5.5" r="2" />
      <path d="M7.2 17.5 C11 14 8 9 12 7 C14 6 15.5 6 17 6.3" />
    </Base>
  )
}

export function IconListOrdered(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M9 6 H20" />
      <path d="M9 12 H20" />
      <path d="M9 18 H20" />
      <path d="M4.5 5 v3" />
      <path d="M4 5 h1" />
      <path d="M4 11 h1.4 c0.6 0 1.1 .4 1.1 1 s-.5 1-1.1 1 H4" />
      <path d="M4 13 h1.4 c0.6 0 1.1 .4 1.1 1 s-.5 1-1.1 1 H4" />
      <path d="M4 17 h2 l-2 2.5 h2" />
    </Base>
  )
}

export function IconSliders(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 6 H20" />
      <path d="M4 12 H20" />
      <path d="M4 18 H20" />
      <circle cx="8" cy="6" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="16" cy="12" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="10" cy="18" r="1.8" fill="currentColor" stroke="none" />
    </Base>
  )
}

export function IconHistory(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 11 a8 8 0 1 0 2.5-5.8" />
      <path d="M4 4 v4 h4" />
      <path d="M12 8 v4 l3 2" />
    </Base>
  )
}

export function IconCheckSquare(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 12.5 L11 15.5 L16.5 9" />
    </Base>
  )
}

export function IconUsers(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 19 c0-3.3 2.5-5.5 5.5-5.5 s5.5 2.2 5.5 5.5" />
      <path d="M16 8.2 a2.6 2.6 0 1 1 0 5.1" />
      <path d="M15.5 13.6 c2.4 .3 4 2.3 4 5.4" />
    </Base>
  )
}

export function IconActivity(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3 12 H7 L9.5 5 L14 19 L16.5 12 H21" />
    </Base>
  )
}

export function IconClock(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5 V12 L15 14" />
    </Base>
  )
}
