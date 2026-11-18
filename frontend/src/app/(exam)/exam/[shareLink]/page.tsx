import { Suspense } from "react";
import { EntryPage } from "@/features/exam/pages/entry-page";

export default async function Page({ params }: { params: Promise<{ shareLink: string }> }) {
  const { shareLink } = await params;
  return (
    <Suspense>
      <EntryPage shareLink={shareLink} />
    </Suspense>
  );
}
