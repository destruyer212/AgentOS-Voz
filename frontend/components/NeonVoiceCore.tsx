interface NeonVoiceCoreProps {
  size?: "sm" | "md" | "lg";
  active?: boolean;
  label?: string;
  className?: string;
}

const SIZE_CLASS = {
  sm: "h-20 w-20",
  md: "h-40 w-40",
  lg: "h-56 w-56",
};

export function NeonVoiceCore({ size = "md", active = true, label, className = "" }: NeonVoiceCoreProps) {
  const animationState = active ? "running" : "paused";

  return (
    <div className={`relative flex items-center justify-center ${SIZE_CLASS[size]} ${className}`}>
      <div className="absolute inset-0 bg-surface-950/20 blur-2xl" />
      <svg
        viewBox="0 0 240 240"
        role="img"
        aria-label={label ?? "Nucleo visual del agente de voz"}
        className="relative h-full w-full overflow-visible"
      >
        <defs>
          <filter id="neon-voice-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feColorMatrix
              in="blur"
              type="matrix"
              values="0 0 0 0 0.30 0 0 0 0 0.85 0 0 0 0 1 0 0 0 0.8 0"
              result="cyanGlow"
            />
            <feMerge>
              <feMergeNode in="cyanGlow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <linearGradient id="neon-core-a" x1="28" y1="48" x2="214" y2="198" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#2dd4bf" />
            <stop offset="0.45" stopColor="#22c8e6" />
            <stop offset="1" stopColor="#f018a8" />
          </linearGradient>
          <linearGradient id="neon-core-b" x1="210" y1="34" x2="42" y2="202" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#f018a8" />
            <stop offset="0.5" stopColor="#8b5cf6" />
            <stop offset="1" stopColor="#4dd8f0" />
          </linearGradient>
          <linearGradient id="neon-core-c" x1="60" y1="210" x2="198" y2="30" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#8b5cf6" />
            <stop offset="0.5" stopColor="#2dd4bf" />
            <stop offset="1" stopColor="#22c8e6" />
          </linearGradient>
        </defs>

        <g className="neon-core-float" style={{ animationPlayState: animationState }}>
          <path
            className="neon-core-line neon-core-line-a"
            d="M50 126C47 62 112 31 163 57C218 86 209 177 151 195C92 214 27 178 50 126Z"
            fill="none"
            stroke="url(#neon-core-a)"
            strokeLinecap="round"
            strokeWidth="5"
            filter="url(#neon-voice-glow)"
            style={{ animationPlayState: animationState }}
          />
          <path
            className="neon-core-line neon-core-line-b"
            d="M70 64C111 41 166 56 195 101C230 157 184 206 122 199C61 192 34 113 70 64Z"
            fill="none"
            stroke="url(#neon-core-b)"
            strokeLinecap="round"
            strokeWidth="4"
            filter="url(#neon-voice-glow)"
            opacity="0.95"
            style={{ animationPlayState: animationState }}
          />
          <path
            className="neon-core-line neon-core-line-c"
            d="M54 156C78 84 128 25 178 63C220 95 202 171 145 193C93 213 38 202 54 156Z"
            fill="none"
            stroke="url(#neon-core-c)"
            strokeLinecap="round"
            strokeWidth="3"
            filter="url(#neon-voice-glow)"
            opacity="0.82"
            style={{ animationPlayState: animationState }}
          />
        </g>

        <circle
          className="neon-core-pulse"
          cx="120"
          cy="120"
          r="7"
          fill="#8be9fd"
          opacity="0.9"
          style={{ animationPlayState: animationState }}
        />
      </svg>
    </div>
  );
}
