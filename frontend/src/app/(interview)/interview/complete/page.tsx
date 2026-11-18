"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useAuthStore } from "@/stores/auth-store";
import { useSessionStore } from "@/stores/session-store";
import { CheckCircle, Download } from "lucide-react";

export default function CompletePage() {
  const router = useRouter();
  const logout = useAuthStore((s) => s.logout);
  const resetSession = useSessionStore((s) => s.reset);
  const [countdown, setCountdown] = useState(8);

  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) { clearInterval(timer); return 0; }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (countdown === 0) {
      resetSession();
      logout();
      router.push("/login");
    }
  }, [countdown, resetSession, logout, router]);

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-lg space-y-5 text-center"
      >
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
        >
          <CheckCircle className="h-20 w-20 text-green-500 mx-auto" />
        </motion.div>

        <h1 className="text-4xl font-bold">Interview Complete!</h1>

        {/* AI message */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="rounded-xl border border-[#00e5ff]/20 bg-[#00e5ff]/5 p-4 text-left space-y-3"
        >
          <p className="text-sm text-white/80 leading-relaxed">
            I won&apos;t forget the joke you told me at the start. Don&apos;t even tell your panel — just give them the uploaded recording link. Let&apos;s keep that joke only between us 🤫
          </p>
          <div className="flex items-center gap-2">
            <Download className="h-4 w-4 text-white/40 shrink-0" />
            <p className="text-sm text-white/50">
              Upload your recording to Google Drive and share the link with your panel member.
            </p>
          </div>
          <p className="text-xs text-white/40 italic">— Yours, Suvera AI</p>
        </motion.div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.55 }}
          className="text-white/30 text-sm"
        >
          Redirecting in {countdown} seconds...
        </motion.p>
      </motion.div>
    </div>
  );
}
