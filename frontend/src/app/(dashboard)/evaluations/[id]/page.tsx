"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/loading-skeleton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { getEvaluation, downloadReport, downloadTranscript } from "@/lib/api/evaluations";
import { Download, CheckCircle, XCircle, Loader2, FileText } from "lucide-react";
import type { EvaluationResult } from "@/types/evaluation";
import { toast } from "sonner";

function _percentageColor(pct: number): string {
  if (pct >= 85) return "text-green-600";
  if (pct >= 70) return "text-blue-600";
  if (pct >= 55) return "text-yellow-600";
  if (pct >= 40) return "text-orange-600";
  return "text-red-600";
}

export default function EvaluationDetailPage() {
  const params = useParams();
  const interviewId = params.id as string;
  const backHref = "/evaluations";
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadingTranscript, setDownloadingTranscript] = useState(false);

  useEffect(() => {
    getEvaluation(interviewId)
      .then(setEvaluation)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [interviewId]);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const response = await downloadReport(interviewId);
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `interview_report_${interviewId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Failed to download report");
    } finally {
      setDownloading(false);
    }
  };

  const handleDownloadTranscript = async () => {
    setDownloadingTranscript(true);
    try {
      const response = await downloadTranscript(interviewId);
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `raw_transcript_${interviewId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Failed to download transcript");
    } finally {
      setDownloadingTranscript(false);
    }
  };

  if (loading) return <PageSkeleton />;
  if (error || !evaluation) return (
    <div className="space-y-4">
      <PageHeader title="Evaluation" backHref={backHref} />
      <p className="text-muted-foreground">Evaluation not available yet. It may still be processing.</p>
    </div>
  );

  const color = _percentageColor(evaluation.percentage);

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Evaluation: ${evaluation.candidate_name}`}
        backHref="/hiring"
        action={
          <div className="flex items-center gap-3">
            {evaluation.is_partial && (
              <Badge variant="outline" className="border-amber-500 text-amber-600 bg-amber-50 text-xs">
                Partially Completed
              </Badge>
            )}
            <Button variant="outline" onClick={handleDownloadTranscript} disabled={downloadingTranscript}>
              {downloadingTranscript ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileText className="mr-2 h-4 w-4" />}
              Raw Transcript
            </Button>
            <Button onClick={handleDownload} disabled={downloading}>
              {downloading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
              Download Report
            </Button>
          </div>
        }
      />

      <div className="grid gap-6 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardContent className="pt-6 flex flex-col items-center space-y-4">
            <div className="relative h-32 w-32">
              <svg className="h-32 w-32 -rotate-90" viewBox="0 0 36 36">
                <path
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  className="text-muted"
                />
                <path
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeDasharray={`${evaluation.percentage}, 100`}
                  className={color}
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-3xl font-bold">{Math.round(evaluation.percentage)}%</span>
              </div>
            </div>
            <p className="text-sm text-muted-foreground">
              {evaluation.total_score} / {evaluation.max_score} points
            </p>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader><CardTitle>Overall Feedback</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm">{evaluation.overall_feedback}</p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h4 className="text-sm font-medium text-green-600 mb-2">Strengths</h4>
                <ul className="text-sm space-y-1">
                  {evaluation.strengths.map((s, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <CheckCircle className="h-4 w-4 text-green-600 mt-0.5 shrink-0" />
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-sm font-medium text-orange-600 mb-2">Areas to Improve</h4>
                <ul className="text-sm space-y-1">
                  {evaluation.areas_for_improvement.map((s, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <XCircle className="h-4 w-4 text-orange-600 mt-0.5 shrink-0" />
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Separator />

      <h2 className="text-lg font-semibold">Question Breakdown</h2>
      <div className="space-y-4">
        {(evaluation.evaluated_results ?? []).map((qe, i) => (
          <Card key={i}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">
                  Q{i + 1}
                </CardTitle>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="text-xs">
                    {qe.asked_by === "ai" ? "Suvera AI" : "Panel"}
                  </Badge>
                  <Badge variant="outline">{qe.score} / 10</Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Question</p>
                <p className="text-sm font-medium">{qe.question}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Candidate Answer</p>
                <p className="text-sm bg-muted/50 p-2 rounded">{qe.answer || "No answer"}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Feedback</p>
                <p className="text-sm">{qe.feedback}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
