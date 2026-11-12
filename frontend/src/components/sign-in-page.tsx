import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Eye, EyeOff, LockKeyhole, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button, Input } from "@/components/ui";
import { authApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth-store";

export function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const setUser = useAuthStore((state) => state.setUser);

  const signIn = useMutation({
    mutationFn: () => authApi.login(email, password),
    onSuccess: (user) => {
      setUser(user);
      queryClient.setQueryData(["session"], user);
      navigate("/", { replace: true });
    },
  });

  const error = signIn.error as { response?: { data?: { detail?: string } } } | null;
  const errorMessage = error?.response?.data?.detail ?? (signIn.isError ? "Unable to sign in. Check the API connection and try again." : "");

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto grid min-h-screen max-w-[1500px] lg:grid-cols-[1.05fr_.95fr]">
        <section className="relative hidden overflow-hidden border-r border-border px-12 py-10 lg:flex lg:flex-col lg:justify-between xl:px-20">
          <div className="absolute inset-0 auth-grid opacity-50" />
          <div className="absolute -left-28 top-[28%] size-[520px] rounded-full bg-violet-600/10 blur-[110px]" />
          <div className="relative flex items-center gap-3">
            <div className="brand-mark"><Sparkles size={19} strokeWidth={1.9} /></div>
            <span className="font-display text-[17px] font-bold tracking-[-.04em]">InsightGPT <span className="text-violet-300">AI</span></span>
          </div>

          <div className="relative max-w-xl pb-10">
            <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-violet-300/15 bg-violet-300/[.06] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[.17em] text-violet-200">
              <span className="size-1.5 rounded-full bg-violet-300 shadow-[0_0_12px_2px_rgba(167,139,250,.5)]" />
              Business intelligence, reimagined
            </div>
            <h1 className="font-display text-[clamp(44px,5.2vw,72px)] font-semibold leading-[1.03] tracking-[-.065em] text-white">
              Ask better.<br />See <span className="gradient-text">further.</span>
            </h1>
            <p className="mt-6 max-w-md text-base leading-7 text-slate-400">
              Your business data, ready for a conversation. InsightGPT turns complex reporting into clear, confident decisions.
            </p>
            <div className="mt-12 flex items-center gap-3 border-t border-white/[.08] pt-6 text-xs text-slate-500">
              <div className="flex -space-x-2">
                <span className="avatar-dot bg-indigo-400" />
                <span className="avatar-dot bg-fuchsia-400" />
                <span className="avatar-dot bg-cyan-400" />
              </div>
              <span>Built for ERP data teams</span>
              <span className="ml-auto flex items-center gap-1.5"><LockKeyhole size={12} /> Private by design</span>
            </div>
          </div>
          <div className="relative flex items-center justify-between text-[11px] text-slate-600">
            <span>© 2026 InsightGPT AI</span>
            <span>Enterprise analytics workspace</span>
          </div>
        </section>

        <section className="flex items-center justify-center px-6 py-12 sm:px-10">
          <div className="w-full max-w-[420px]">
            <div className="mb-11 flex items-center gap-3 lg:hidden">
              <div className="brand-mark"><Sparkles size={18} /></div>
              <span className="font-display text-lg font-bold tracking-[-.04em]">InsightGPT <span className="text-violet-300">AI</span></span>
            </div>
            <div className="mb-9">
              <div className="mb-5 inline-flex size-12 items-center justify-center rounded-2xl border border-white/[.09] bg-white/[.04] text-violet-200 shadow-inner">
                <LockKeyhole size={19} />
              </div>
              <h2 className="font-display text-[32px] font-semibold tracking-[-.055em] text-white">Welcome back</h2>
              <p className="mt-2 text-sm leading-6 text-slate-400">Sign in to continue to your analytics workspace.</p>
            </div>

            <form className="space-y-5" onSubmit={(event) => { event.preventDefault(); signIn.mutate(); }}>
              <label className="block space-y-2 text-[13px] font-medium text-slate-300">
                Work email
                <Input autoComplete="username" type="email" placeholder="you@company.com" value={email} onChange={(event) => setEmail(event.target.value)} required />
              </label>
              <label className="block space-y-2 text-[13px] font-medium text-slate-300">
                Password
                <span className="relative block">
                  <Input autoComplete="current-password" type={showPassword ? "text" : "password"} placeholder="Enter your password" value={password} onChange={(event) => setPassword(event.target.value)} required className="pr-12" />
                  <button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((visible) => !visible)} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-500 hover:text-slate-300">
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>
              {errorMessage && <p role="alert" className="rounded-xl border border-rose-400/20 bg-rose-400/[.07] px-3.5 py-3 text-sm text-rose-200">{errorMessage}</p>}
              <Button type="submit" disabled={signIn.isPending} className="mt-1 w-full">
                {signIn.isPending ? "Signing in…" : "Sign in"}
                {!signIn.isPending && <ArrowRight size={16} />}
              </Button>
            </form>
            <p className="mt-6 text-center text-xs leading-5 text-slate-500">Need an account? Ask your InsightGPT administrator for access.</p>
            <p className="mt-12 text-center text-[11px] text-slate-600">Authentication protected · Your credentials stay private</p>
          </div>
        </section>
      </div>
    </main>
  );
}
