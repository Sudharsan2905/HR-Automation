import { CompletedPage } from "@/features/exam/pages/completed-page";

export default async function Page({ params }: { params: Promise<{ shareLink: string }> }) {
  const { shareLink } = await params;
  return <CompletedPage shareLink={shareLink} />;
}
