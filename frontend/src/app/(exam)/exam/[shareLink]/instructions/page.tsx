import { InstructionsPage } from "@/features/exam/pages/instructions-page";

export default async function Page({ params }: { params: Promise<{ shareLink: string }> }) {
  const { shareLink } = await params;
  return <InstructionsPage shareLink={shareLink} />;
}
