export function BrandMark({ className = '', decorative = false, title = 'JobTomatik' }) {
  return (
    <svg
      viewBox="0 0 108 108"
      className={className}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative ? 'true' : undefined}
      aria-label={decorative ? undefined : title}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="jt-shell" x1="10" y1="8" x2="98" y2="102" gradientUnits="userSpaceOnUse">
          <stop stopColor="#162A4A" />
          <stop offset="1" stopColor="#07111F" />
        </linearGradient>
        <linearGradient id="jt-blue" x1="41" y1="43" x2="66" y2="87" gradientUnits="userSpaceOnUse">
          <stop stopColor="#78B3FF" />
          <stop offset="1" stopColor="#2F6BFF" />
        </linearGradient>
        <linearGradient id="jt-gold" x1="74" y1="15" x2="97" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FFD66B" />
          <stop offset="1" stopColor="#E8A92B" />
        </linearGradient>
        <filter id="jt-shadow" x="-20%" y="-20%" width="140%" height="150%">
          <feDropShadow dx="0" dy="4" stdDeviation="4" floodColor="#000" floodOpacity=".32" />
        </filter>
      </defs>

      <rect x="3" y="3" width="102" height="102" rx="26" fill="url(#jt-shell)" />
      <rect x="4" y="4" width="100" height="100" rx="25" fill="none" stroke="#284A78" strokeOpacity=".55" />

      <g filter="url(#jt-shadow)">
        <path d="M18 42h24" stroke="url(#jt-blue)" strokeWidth="6" strokeLinecap="round" />
        <path d="M13 53h24" stroke="url(#jt-blue)" strokeWidth="6" strokeLinecap="round" opacity=".9" />

        <path
          d="M48 22h31v43c0 17-10.7 27-26.5 27S27 82.2 27 68V59h17v8.5c0 5.8 3.3 9.7 8.8 9.7 5.8 0 9.2-4.1 9.2-11.2V38H48V22Z"
          fill="#F8FAFC"
        />
        <path d="M52.5 55 59 62l-6.5 8-6.5-8 6.5-7Z" fill="#78B3FF" />
        <path d="m52.5 67 7.5 17-7.5 8-7.5-8 7.5-17Z" fill="url(#jt-blue)" />

        <g fill="url(#jt-gold)">
          <circle cx="82" cy="28" r="12" />
          <rect x="79" y="11" width="6" height="9" rx="2" />
          <rect x="79" y="36" width="6" height="9" rx="2" />
          <rect x="65" y="25" width="9" height="6" rx="2" />
          <rect x="90" y="25" width="9" height="6" rx="2" />
          <rect x="69" y="15" width="6" height="9" rx="2" transform="rotate(-45 69 15)" />
          <rect x="91" y="33" width="6" height="9" rx="2" transform="rotate(-45 91 33)" />
          <rect x="91" y="15" width="6" height="9" rx="2" transform="rotate(45 91 15)" />
          <rect x="69" y="33" width="6" height="9" rx="2" transform="rotate(45 69 33)" />
        </g>
        <circle cx="82" cy="28" r="5.2" fill="#10213A" />
      </g>
    </svg>
  )
}

export function BrandWordmark({ className = '', compact = false }) {
  return (
    <div className={`inline-flex items-center gap-3 ${className}`.trim()}>
      <BrandMark className={compact ? 'h-8 w-8' : 'h-10 w-10'} decorative />
      <span className={`${compact ? 'text-base' : 'text-xl'} font-extrabold tracking-[-0.03em] text-white`}>
        Job<span className="brand-gradient-text">Tomatik</span>
      </span>
    </div>
  )
}
