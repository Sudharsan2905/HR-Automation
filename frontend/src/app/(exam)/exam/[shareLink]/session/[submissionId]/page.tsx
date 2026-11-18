import { SessionPage } from "@/features/exam/pages/session-page";

export default async function Page({
  params,
}: {
  params: Promise<{ shareLink: string; submissionId: string }>;
}) {
  const { shareLink, submissionId } = await params;
  return <SessionPage shareLink={shareLink} submissionId={submissionId} />;
}
