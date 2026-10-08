import { useId } from "react";

/**
 * The Weave app mark: a W folded from one ribbon.
 *
 * Four sheared strips alternate light and deep teal, so each turn of the W
 * reads as a fold in fabric, and the amber point above the middle peak is the
 * same accent that rides the wordmark's trace. Geometry matches
 * public/icon.svg exactly, which is also the source of the desktop and tray
 * icons, so every surface shows the same mark.
 */
export default function WeaveGlyph({
  size = 20,
  className = "",
  title,
}: {
  size?: number;
  className?: string;
  title?: string;
}) {
  // Gradient ids must be unique per instance or two marks on a page share one.
  const id = useId().replace(/:/g, "");
  const strip = (a: [number, number], b: [number, number]) =>
    `${a[0] - 31},${a[1]} ${a[0] + 31},${a[1]} ${b[0] + 31},${b[1]} ${b[0] - 31},${b[1]}`;
  const T0: [number, number] = [118, 142];
  const B0: [number, number] = [190, 378];
  const M: [number, number] = [256, 236];
  const B1: [number, number] = [322, 378];
  const T2: [number, number] = [394, 142];

  return (
    <svg
      viewBox="0 0 512 512"
      width={size}
      height={size}
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <defs>
        <linearGradient id={`${id}bg`} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="512" y2="512">
          <stop offset="0" stopColor="#17404a" />
          <stop offset="1" stopColor="#0a1820" />
        </linearGradient>
        <linearGradient id={`${id}lite`} gradientUnits="userSpaceOnUse" x1="0" y1="140" x2="0" y2="380">
          <stop offset="0" stopColor="#a6f5e8" />
          <stop offset="1" stopColor="#45c7b8" />
        </linearGradient>
        <linearGradient id={`${id}deep`} gradientUnits="userSpaceOnUse" x1="0" y1="140" x2="0" y2="380">
          <stop offset="0" stopColor="#2bb3a4" />
          <stop offset="1" stopColor="#0f6d65" />
        </linearGradient>
        <linearGradient id={`${id}spark`} gradientUnits="userSpaceOnUse" x1="232" y1="110" x2="280" y2="170">
          <stop offset="0" stopColor="#ffd98a" />
          <stop offset="1" stopColor="#f28c2e" />
        </linearGradient>
      </defs>
      <rect width="512" height="512" rx="116" fill={`url(#${id}bg)`} />
      <polygon points={strip(T0, B0)} fill={`url(#${id}lite)`} />
      <polygon points={strip(B0, M)} fill={`url(#${id}deep)`} />
      <polygon points={strip(M, B1)} fill={`url(#${id}lite)`} />
      <polygon points={strip(B1, T2)} fill={`url(#${id}deep)`} />
      <circle cx="256" cy="150" r="27" fill={`url(#${id}spark)`} />
    </svg>
  );
}
