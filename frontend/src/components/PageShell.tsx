/**
 * Scrollable page container for non-chat pages (chat is full-bleed, own scroll).
 *
 * `pad-chrome-top` is not decoration: AppShell draws the menu / sidebar-reveal
 * button as a FIXED overlay at the top-left, so without this reservation the
 * first heading of every page renders underneath it. One variable
 * (--chrome-top) means the clearance stays correct if the button ever moves.
 */
export default function PageShell({
  children,
  size = "content",
}: {
  children: React.ReactNode;
  size?: "content" | "chat" | "narrow" | "wide";
}) {
  const max =
    size === "chat"
      ? "max-w-chat"
      : size === "narrow"
        ? "max-w-md"
        : size === "wide"
          ? "max-w-6xl"
          : "max-w-content";
  return (
    <div className="h-full overflow-y-auto overflow-x-hidden">
      <div
        className={`pad-chrome-top mx-auto w-full min-w-0 ${max} px-4 pb-10 sm:px-6 sm:pb-14`}
        style={{ paddingBottom: "calc(2.5rem + var(--safe-bottom))" }}
      >
        {children}
      </div>
    </div>
  );
}
