import { getLanguage, isAuthed } from "@/lib/session";
import { redirect } from "next/navigation";
import PageShell from "@/components/PageShell";
import AdminClient from "@/components/AdminClient";

// Admin / ops dashboard (architecture 4.2 /admin) — real data from /admin/* API,
// gated server-side to authed users; the API itself enforces admin/institutional.
export default async function AdminPage() {
  if (!(await isAuthed())) redirect("/auth/login");
  await getLanguage();
  return (
    <PageShell>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Admin / Ops</h1>
      <p className="mb-6 text-sm text-fg-muted">
        Ingestion, sandbox audit log, and library status (architecture §7.4 / §8.4).
      </p>
      <AdminClient />
    </PageShell>
  );
}
