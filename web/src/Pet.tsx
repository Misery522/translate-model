export function Pet({ state = 'idle', large = false }: { state?: 'idle' | 'thinking' | 'offline'; large?: boolean }) {
  return <div className={`pet pet--${state} ${large ? 'pet--large' : ''}`} aria-hidden="true">
    <svg viewBox="0 0 128 128" fill="none">
      <ellipse cx="64" cy="113" rx="32" ry="6" fill="#d9e2d3" />
      <path d="M31 45 27 23q0-6 6-3l20 16q12-4 23 0l20-16q6-3 6 3l-4 22q11 15 10 31c-2 23-20 35-44 35S22 99 20 76q-1-16 11-31Z" fill="#b6cfaa" stroke="#365548" strokeWidth="3.5" />
      <path d="m35 32 11 10-10 3m56-13-11 10 10 3" fill="#e8eee2" />
      {state === 'offline' ? <g stroke="#365548" strokeWidth="4" strokeLinecap="round"><path d="m40 69 11 1m26 0 11-1" /></g> : <g fill="#365548" className="pet-eyes"><ellipse cx="46" cy="67" rx="4.5" ry="6.5" /><ellipse cx="82" cy="67" rx="4.5" ry="6.5" /></g>}
      <path d={state === 'offline' ? 'M60 87q4-3 8 0' : 'm59 83 5 4 5-4'} stroke="#365548" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
      <ellipse cx="34" cy="81" rx="8" ry="4.5" fill="#e6b4a5" /><ellipse cx="94" cy="81" rx="8" ry="4.5" fill="#e6b4a5" />
      {state === 'thinking' && <g className="pet-thought" fill="#7a9470"><circle cx="111" cy="33" r="4" /><circle cx="115" cy="20" r="6" /></g>}
    </svg>
  </div>;
}
