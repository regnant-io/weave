// Scrollable page container for non-chat pages (chat is full-bleed, own scroll).
export default function PageShell({
  children,
  size = "content",
}: {
  children: React.ReactNode;
  size?: "content" | "chat" | "narrow";
}) {
  const max = size === "chat" ? "max-w-chat" : size === "narrow" ? "max-w-md" : "max-w-content";
  return (
    <div className="h-full overflow-y-auto">
      <div className={`mx-auto w-full ${max} px-4 py-8 sm:py-10`}>{children}</div>
    </div>
  );
}
