"use client";

/**
 * The 4-step apply wizard, wired directly to:
 *   POST  /merchants/apply/start
 *   PATCH /merchants/apply/resume/{token}/business
 *   PATCH /merchants/apply/resume/{token}/verification
 *   POST  /merchants/apply/resume/{token}/submit
 *   GET   /merchants/apply/resume/{token}   (repopulate on reload)
 *
 * State model: `token` and `step` live in the URL query string
 * (?token=...&step=N) so a reload or a "continue your application" email
 * link both land correctly. On every mount where a token is present, we
 * call GET .../apply/resume/{token} to repopulate fields — per the backend
 * comment, skipping this silently blanks out anything already entered.
 */

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ApiError,
  applyResume,
  applyStepFour,
  applyStepOne,
  applyStepThree,
  applyStepTwo,
  type ResumeState,
} from "@/lib/api";

const TERMS_VERSION = "v1"; // bump when terms copy changes; must match what's shown to the user

type WizardData = Partial<ResumeState>;

export default function GetStartedPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <Wizard />
    </Suspense>
  );
}

function Wizard() {
  const router = useRouter();
  const params = useSearchParams();
  const urlToken = params.get("token");
  const urlStep = Number(params.get("step") ?? "1");

  const [token, setToken] = useState<string | null>(urlToken);
  const [step, setStep] = useState<number>(urlToken ? urlStep || 1 : 1);
  const [data, setData] = useState<WizardData>({});
  const [loadingResume, setLoadingResume] = useState<boolean>(!!urlToken);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  // Repopulate from the backend whenever we have a token — on first mount
  // from a URL param, and again any time the token changes (e.g. just
  // issued by step 1).
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoadingResume(true);
    setResumeError(null);
    applyResume(token)
      .then((state) => {
        if (cancelled) return;
        setData(state);
        setStep(state.current_step);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError) {
          setResumeError(err.message);
        } else {
          setResumeError("Couldn't load your application. Please try again.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingResume(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  function goToStep(nextStep: number, nextToken: string) {
    setStep(nextStep);
    setToken(nextToken);
    router.replace(`/get-started?token=${encodeURIComponent(nextToken)}&step=${nextStep}`);
  }

  if (submitted) {
    return (
      <main className="page">
        <h1>Application submitted</h1>
        <p className="subtitle">
          Thanks — we&rsquo;ve got your application. Our team will review it
          and reach out by email or WhatsApp within 1&ndash;2 business days.
          Once approved, you&rsquo;ll get an email to set your password and
          sign in.
        </p>
      </main>
    );
  }

  if (loadingResume) {
    return <main className="page">Loading your application&hellip;</main>;
  }

  if (resumeError) {
    return (
      <main className="page">
        <h1>We couldn&rsquo;t open that application</h1>
        <p className="banner-error">{resumeError}</p>
        <button className="btn" onClick={() => (window.location.href = "/get-started")}>
          Start a new application
        </button>
      </main>
    );
  }

  return (
    <main className="page">
      <h1>Apply to onboard your hotel</h1>
      <StepIndicator step={step} />

      {step === 1 && (
        <StepOne
          data={data}
          onNext={(result, submittedData) => {
            setData((d) => ({ ...d, ...submittedData }));
            goToStep(result.current_step, result.resume_token);
          }}
        />
      )}

      {step === 2 && token && (
        <StepTwo
          token={token}
          data={data}
          onNext={(result, submittedData) => {
            setData((d) => ({ ...d, ...submittedData, registration_status: result.registration_status as ResumeState["registration_status"] }));
            setStep(result.current_step);
            router.replace(`/get-started?token=${encodeURIComponent(token)}&step=${result.current_step}`);
          }}
        />
      )}

      {step === 3 && token && (
        <StepThree
          token={token}
          registrationStatus={data.registration_status ?? "unregistered"}
          onNext={(result) => {
            setStep(result.current_step);
            router.replace(`/get-started?token=${encodeURIComponent(token)}&step=${result.current_step}`);
          }}
        />
      )}

      {step === 4 && token && (
        <StepFour token={token} onDone={() => setSubmitted(true)} />
      )}
    </main>
  );
}

function StepIndicator({ step }: { step: number }) {
  return (
    <div className="steps" aria-label={`Step ${step} of 4`}>
      {[1, 2, 3, 4].map((n) => (
        <div key={n} className={`step-dot ${n <= step ? "active" : ""}`} />
      ))}
    </div>
  );
}

// ── Step 1: contact details ─────────────────────────────────────────────

function StepOne({
  data,
  onNext,
}: {
  data: WizardData;
  onNext: (
    result: { application_id: string; resume_token: string; current_step: number },
    submitted: WizardData
  ) => void;
}) {
  const [fullName, setFullName] = useState(data.full_name ?? "");
  const [email, setEmail] = useState(data.email ?? "");
  const [phone, setPhone] = useState(data.phone_number ?? "");
  const [whatsapp, setWhatsapp] = useState(data.whatsapp_number ?? "");
  const [website, setWebsite] = useState(""); // honeypot — must stay empty
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await applyStepOne({
        full_name: fullName,
        email,
        phone_number: phone,
        whatsapp_number: whatsapp || null,
        website,
      });
      onNext(result, {
        full_name: fullName,
        email,
        phone_number: phone,
        whatsapp_number: whatsapp || null,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && <div className="banner-error">{error}</div>}

      <div className="field">
        <label htmlFor="full_name">Your full name</label>
        <input
          id="full_name"
          required
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
      </div>

      <div className="field">
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>

      <div className="field">
        <label htmlFor="phone">Phone number</label>
        <input
          id="phone"
          required
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="e.g. 08012345678"
        />
      </div>

      <div className="field">
        <label htmlFor="whatsapp">WhatsApp number (optional)</label>
        <input
          id="whatsapp"
          value={whatsapp ?? ""}
          onChange={(e) => setWhatsapp(e.target.value)}
          placeholder="If different from phone number"
        />
        <div className="field-hint">
          If left blank, we&rsquo;ll email you a link to add it later.
        </div>
      </div>

      {/* Honeypot — never shown to real users */}
      <div className="hp-field" aria-hidden="true">
        <label htmlFor="website">Website</label>
        <input
          id="website"
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
        />
      </div>

      <button className="btn" type="submit" disabled={busy}>
        {busy ? "Submitting…" : "Continue"}
      </button>
    </form>
  );
}

// ── Step 2: business details ────────────────────────────────────────────

function StepTwo({
  token,
  data,
  onNext,
}: {
  token: string;
  data: WizardData;
  onNext: (
    result: { current_step: number; registration_status: string },
    submitted: WizardData
  ) => void;
}) {
  const [businessName, setBusinessName] = useState(data.business_name ?? "");
  const [businessType, setBusinessType] = useState(data.business_type ?? "");
  const [cityState, setCityState] = useState(data.city_state ?? "");
  const [registrationStatus, setRegistrationStatus] = useState<
    "registered" | "unregistered"
  >(data.registration_status ?? "registered");
  const [numBranches, setNumBranches] = useState(data.num_branches ?? 1);
  const [monthlyVolume, setMonthlyVolume] = useState(data.monthly_order_volume ?? "");
  const [usesWhatsappManual, setUsesWhatsappManual] = useState(
    data.uses_whatsapp_manual ?? false
  );
  const [usesDelivery, setUsesDelivery] = useState(data.uses_delivery_service ?? false);
  const [heardAboutUs, setHeardAboutUs] = useState(data.heard_about_us ?? "");
  const [comments, setComments] = useState(data.comments ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const payload = {
        business_name: businessName,
        business_type: businessType,
        city_state: cityState,
        registration_status: registrationStatus,
        num_branches: numBranches,
        monthly_order_volume: monthlyVolume || null,
        uses_whatsapp_manual: usesWhatsappManual,
        uses_delivery_service: usesDelivery,
        heard_about_us: heardAboutUs || null,
        comments: comments || null,
      };
      const result = await applyStepTwo(token, payload);
      onNext(result, payload as WizardData);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && <div className="banner-error">{error}</div>}

      <div className="field">
        <label htmlFor="business_name">Hotel / business name</label>
        <input
          id="business_name"
          required
          value={businessName}
          onChange={(e) => setBusinessName(e.target.value)}
        />
      </div>

      <div className="field">
        <label htmlFor="business_type">Business type</label>
        <input
          id="business_type"
          required
          value={businessType}
          onChange={(e) => setBusinessType(e.target.value)}
          placeholder="e.g. Hotel, Guesthouse, Serviced Apartments"
        />
      </div>

      <div className="field">
        <label htmlFor="city_state">City / State</label>
        <input
          id="city_state"
          required
          value={cityState}
          onChange={(e) => setCityState(e.target.value)}
        />
      </div>

      <div className="field">
        <label htmlFor="registration_status">Is the business formally registered (CAC)?</label>
        <select
          id="registration_status"
          value={registrationStatus}
          onChange={(e) =>
            setRegistrationStatus(e.target.value as "registered" | "unregistered")
          }
        >
          <option value="registered">Yes, registered with CAC</option>
          <option value="unregistered">No, not yet registered</option>
        </select>
      </div>

      <div className="field">
        <label htmlFor="num_branches">Number of branches</label>
        <input
          id="num_branches"
          type="number"
          min={1}
          required
          value={numBranches}
          onChange={(e) => setNumBranches(Number(e.target.value))}
        />
      </div>

      <div className="field">
        <label htmlFor="monthly_volume">Estimated monthly bookings (optional)</label>
        <input
          id="monthly_volume"
          value={monthlyVolume ?? ""}
          onChange={(e) => setMonthlyVolume(e.target.value)}
        />
      </div>

      <div className="checkbox-row">
        <input
          id="uses_whatsapp_manual"
          type="checkbox"
          checked={usesWhatsappManual}
          onChange={(e) => setUsesWhatsappManual(e.target.checked)}
        />
        <label htmlFor="uses_whatsapp_manual">
          We currently take bookings manually over WhatsApp
        </label>
      </div>

      <div className="checkbox-row">
        <input
          id="uses_delivery"
          type="checkbox"
          checked={usesDelivery}
          onChange={(e) => setUsesDelivery(e.target.checked)}
        />
        <label htmlFor="uses_delivery">We offer airport/pickup or delivery service</label>
      </div>

      <div className="field">
        <label htmlFor="heard_about_us">How did you hear about us? (optional)</label>
        <input
          id="heard_about_us"
          value={heardAboutUs ?? ""}
          onChange={(e) => setHeardAboutUs(e.target.value)}
        />
      </div>

      <div className="field">
        <label htmlFor="comments">Anything else we should know? (optional)</label>
        <textarea
          id="comments"
          rows={3}
          value={comments ?? ""}
          onChange={(e) => setComments(e.target.value)}
        />
      </div>

      <button className="btn" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Continue"}
      </button>
    </form>
  );
}

// ── Step 3: verification ────────────────────────────────────────────────

function StepThree({
  token,
  registrationStatus,
  onNext,
}: {
  token: string;
  registrationStatus: "registered" | "unregistered";
  onNext: (result: { current_step: number }) => void;
}) {
  const [cacNumber, setCacNumber] = useState("");
  const [method, setMethod] = useState<"bvn" | "nin">("nin");
  const [bvn, setBvn] = useState("");
  const [nin, setNin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const payload =
        registrationStatus === "registered"
          ? { cac_number: cacNumber }
          : method === "bvn"
          ? ({ verification_method: "bvn", bvn } as const)
          : ({ verification_method: "nin", nin } as const);

      const result = await applyStepThree(token, payload);
      onNext(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && <div className="banner-error">{error}</div>}

      {registrationStatus === "registered" ? (
        <div className="field">
          <label htmlFor="cac_number">CAC RC/BN number</label>
          <input
            id="cac_number"
            required
            value={cacNumber}
            onChange={(e) => setCacNumber(e.target.value)}
          />
        </div>
      ) : (
        <>
          <div className="field">
            <label htmlFor="method">Verify with</label>
            <select
              id="method"
              value={method}
              onChange={(e) => setMethod(e.target.value as "bvn" | "nin")}
            >
              <option value="nin">NIN</option>
              <option value="bvn">BVN</option>
            </select>
          </div>
          {method === "nin" ? (
            <div className="field">
              <label htmlFor="nin">NIN</label>
              <input id="nin" required value={nin} onChange={(e) => setNin(e.target.value)} />
            </div>
          ) : (
            <div className="field">
              <label htmlFor="bvn">BVN</label>
              <input id="bvn" required value={bvn} onChange={(e) => setBvn(e.target.value)} />
            </div>
          )}
        </>
      )}

      <div className="field-hint" style={{ marginBottom: 16 }}>
        This is used to verify your identity. It doesn&rsquo;t affect your
        application even while under manual review.
      </div>

      <button className="btn" type="submit" disabled={busy}>
        {busy ? "Verifying…" : "Continue"}
      </button>
    </form>
  );
}

// ── Step 4: terms & submit ──────────────────────────────────────────────

function StepFour({ token, onDone }: { token: string; onDone: () => void }) {
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await applyStepFour(token, TERMS_VERSION);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && <div className="banner-error">{error}</div>}

      <div className="checkbox-row">
        <input
          id="terms"
          type="checkbox"
          checked={agreed}
          onChange={(e) => setAgreed(e.target.checked)}
        />
        <label htmlFor="terms">
          I agree to the <a href="/terms" target="_blank">terms of service</a> and confirm the
          information provided is accurate.
        </label>
      </div>

      <button className="btn" type="submit" disabled={busy || !agreed}>
        {busy ? "Submitting…" : "Submit application"}
      </button>
    </form>
  );
}
