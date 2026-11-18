"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { login, candidateLogin } from "@/lib/api/auth";
import { getAudioCheck } from "@/lib/api/session";
import { useAuthStore } from "@/stores/auth-store";
import { useSessionStore } from "@/stores/session-store";
import { candidateScope, decodeJwt } from "@/lib/utils";
import { ROLE_HOME } from "@/lib/constants";
import { toast } from "sonner";
import { Loader2, Eye, EyeOff } from "lucide-react";

// Only same-site /exam links may be used as a post-login destination.
function safeExamNext(next: string | null): string | null {
  if (!next) return null;
  return /^\/exam(\/[A-Za-z0-9_\-./~%]*)?(\?[^\s]*)?$/.test(next) ? next : null;
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeExamNext(searchParams.get("next"));
  const setAuth = useAuthStore((s) => s.setAuth);
  const [tab, setTab] = useState<string>(next ? "candidate" : "admin");
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ email: "", password: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [candidate, setCandidate] = useState({ email: "", accessKey: "" });

  const handleAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await login({ email: form.email.trim(), password: form.password });
      const payload = decodeJwt(res.access_token);
      setAuth(res.access_token, res.role, payload?.email || form.email, payload?.full_name);
      toast.success("Login successful");
      router.push(ROLE_HOME[res.role] || "/dashboard");
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message || "Login failed";
      toast.error(msg.toLowerCase().includes("invalid") ? "Invalid email or password." : msg);
    } finally {
      setLoading(false);
    }
  };

  const handleCandidate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!candidate.accessKey.trim()) return toast.error("Enter your access key");
    setLoading(true);
    try {
      const email = candidate.email.trim().toLowerCase();
      const res = await candidateLogin({ email, access_key: candidate.accessKey.trim() });
      const payload = decodeJwt(res.access_token);
      setAuth(res.access_token, res.role, payload?.email || email, payload?.full_name);
      const scope = candidateScope(payload?.scope);
      toast.success("Login successful");
      if (scope === "l2") {
        // Pre-fetch the audio check so it is ready when the lobby opens
        getAudioCheck()
          .then((data) => useSessionStore.getState().setPreparedAudioCheck(data))
          .catch(() => { /* the lobby fetches it on demand */ });
        router.push("/interview/lobby");
      } else {
        router.push(next || "/exam");
      }
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message || "";
      toast.error(msg.toLowerCase().includes("expired")
        ? "Access key expired. Ask the hiring team for a new key."
        : "Invalid email or access key.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-2xl">Welcome to SkillMate</CardTitle>
        <CardDescription>Sign in to continue</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="mb-4 grid w-full grid-cols-2">
            <TabsTrigger value="admin">Admin</TabsTrigger>
            <TabsTrigger value="candidate">Candidate</TabsTrigger>
          </TabsList>

          <TabsContent value="admin">
            <form onSubmit={handleAdmin} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="admin@company.com"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    required
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <Button type="submit" className="w-full" disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Sign In
              </Button>
            </form>
          </TabsContent>

          <TabsContent value="candidate">
            <form onSubmit={handleCandidate} className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Use the email your invitation was sent to and the access key from it. Level 1 and Level 2 have different keys.
              </p>
              <div className="space-y-2">
                <Label htmlFor="c-email">Email</Label>
                <Input
                  id="c-email"
                  type="email"
                  placeholder="you@example.com"
                  value={candidate.email}
                  onChange={(e) => setCandidate({ ...candidate, email: e.target.value })}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="access-key">Access Key</Label>
                <Input
                  id="access-key"
                  className="font-mono"
                  placeholder="Paste your access key here"
                  value={candidate.accessKey}
                  onChange={(e) => setCandidate({ ...candidate, accessKey: e.target.value })}
                  required
                />
              </div>
              <Button type="submit" className="w-full" disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Continue
              </Button>
            </form>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
