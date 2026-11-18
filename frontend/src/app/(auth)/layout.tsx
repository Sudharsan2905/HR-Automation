export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="hidden lg:flex items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-[#7c3aed]/30">
        <div className="text-center space-y-4 px-8">
          <h1 className="text-4xl font-bold text-white">
            Skill<span className="text-[#00e5ff]">Mate</span>
          </h1>
          <p className="text-[11px] italic text-slate-500 tracking-wide">Product by Softsuave&apos;s AI team</p>
          <p className="text-slate-400 text-lg max-w-md mt-3">
            AI-powered interview platform for smarter hiring
          </p>
        </div>
      </div>
      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-md">{children}</div>
      </div>
    </div>
  );
}
