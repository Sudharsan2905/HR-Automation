"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/loading-skeleton";
import { StatusBadge } from "@/components/shared/status-dot";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { getInterview, deleteInterview } from "@/lib/api/interviews";
import { formatDate } from "@/lib/utils";
import { BarChart3, Trash2 } from "lucide-react";
import type { InterviewDetail } from "@/types/interview";
import { toast } from "sonner";

export default function InterviewDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [interview, setInterview] = useState<InterviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const fetchInterview = useCallback(async () => {
    try {
      const data = await getInterview(id);
      setInterview(data);
    } catch {
      toast.error("Failed to load interview");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchInterview(); }, [fetchInterview]);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteInterview(id);
      toast.success("Interview deleted");
      router.push("/hiring");
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message || "Failed to delete");
    } finally {
      setDeleting(false);
    }
  };

  if (loading || !interview) return <PageSkeleton />;

  return (
    <div className="space-y-6">
      <PageHeader
        title={interview.title || "Interview"}
        description={`${interview.num_questions} questions · ${formatDate(interview.created_at)}`}
        action={<StatusBadge status={interview.status} />}
        backHref="/hiring"
      />

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <span><span className="font-semibold text-foreground">Candidate:</span> <span className="text-muted-foreground">{interview.candidate_mail}</span></span>
        {interview.domain_title && <span><span className="font-semibold text-foreground">Domain:</span> <span className="text-muted-foreground">{interview.domain_title}</span></span>}
        {interview.difficulty_level && <span><span className="font-semibold text-foreground">Difficulty:</span> <span className="text-muted-foreground">{interview.difficulty_level}</span></span>}
        {interview.due_date && <span><span className="font-semibold text-foreground">Due:</span> <span className="text-muted-foreground">{formatDate(interview.due_date)}</span></span>}
      </div>

      {interview.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {interview.tags.map((t) => (
            <Badge key={t} variant="secondary">{t}</Badge>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        {interview.status === "finalized" && (
          <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
            <Trash2 className="mr-2 h-4 w-4" /> Delete Interview
          </Button>
        )}
        {(interview.status === "completed" || interview.status === "partially_completed") && (
          <Button asChild>
            <Link href={`/evaluations/${interview.id}`}>
              <BarChart3 className="mr-2 h-4 w-4" /> View Evaluation
            </Link>
          </Button>
        )}
      </div>

      <Separator />

      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Questions</h2>
        {interview.questions?.map((q, i) => (
          <Card key={q.id}>
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2">
                <CardTitle className="text-base">Question {i + 1}</CardTitle>
                <Badge variant="outline">{q.topic}</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm">{q.question}</p>
              {q.expected_points.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1">Expected Points:</p>
                  <ul className="text-sm text-muted-foreground list-disc list-inside space-y-0.5">
                    {q.expected_points.map((p, j) => <li key={j}>{p}</li>)}
                  </ul>
                </div>
              )}
              {q.follow_ups.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1">Follow-ups:</p>
                  <ul className="text-sm text-muted-foreground list-disc list-inside space-y-0.5">
                    {q.follow_ups.map((f) => <li key={f.id}>{f.question}</li>)}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete Interview"
        description="This will permanently delete this interview. Are you sure?"
        confirmLabel="Delete"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}
