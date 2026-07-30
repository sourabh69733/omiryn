import {
  ArrowLeft,
  ArrowRight,
  Camera,
  Check,
  CheckCircle2,
  ChevronDown,
  ImagePlus,
  LockKeyhole,
  MapPin,
  Smartphone,
  Sparkles,
  ShieldCheck,
  UserRound,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { OmirynLogo } from "../brand/OmirynLogo";

type Gender = "man" | "woman" | "non_binary" | "prefer_not_to_say" | "";
type InterestedIn = "women" | "men" | "everyone" | "";

type SetupValues = {
  displayName: string;
  dob: string;
  gender: Gender;
  interestedIn: InterestedIn;
  city: string;
  phone: string;
};

type AuthUser = {
  display_name?: string | null;
};

type PhotoValue = {
  file: File;
  url: string;
};

type LocationData = {
  states?: Array<{ code: string; name: string }>;
  citiesByState?: Record<string, Array<{ name: string; population?: number }>>;
};

const STORAGE_KEY = "omiryn-profile-setup";

const steps = [
  { title: "About you", summary: "The basics that identify your profile", icon: UserRound, optional: false },
  { title: "Matching preferences", summary: "Who and where you would like to meet", icon: Sparkles, optional: false },
  { title: "Photos", summary: "Add up to four profile photos", icon: Camera, optional: true },
  { title: "Mobile", summary: "A private number for your account", icon: Smartphone, optional: true }
] as const;

const genderOptions: Array<{ value: Exclude<Gender, "">; label: string }> = [
  { value: "man", label: "Man" },
  { value: "woman", label: "Woman" },
  { value: "non_binary", label: "Non-binary" },
  { value: "prefer_not_to_say", label: "Prefer not to say" }
];

const interestOptions: Array<{ value: Exclude<InterestedIn, "">; label: string; note: string }> = [
  { value: "women", label: "Women", note: "Meet women" },
  { value: "men", label: "Men", note: "Meet men" },
  { value: "everyone", label: "Everyone", note: "Stay open" }
];

const emptyValues: SetupValues = {
  displayName: "",
  dob: "",
  gender: "",
  interestedIn: "",
  city: "",
  phone: ""
};

function readSavedValues(): SetupValues {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved ? { ...emptyValues, ...JSON.parse(saved) } : emptyValues;
  } catch {
    return emptyValues;
  }
}

function dateYearsAgo(years: number) {
  const date = new Date();
  date.setFullYear(date.getFullYear() - years);
  return date.toISOString().slice(0, 10);
}

function ageFromDob(value: string) {
  if (!value) return null;
  const birthDate = new Date(`${value}T00:00:00`);
  if (Number.isNaN(birthDate.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - birthDate.getFullYear();
  if (
    now.getMonth() < birthDate.getMonth() ||
    (now.getMonth() === birthDate.getMonth() && now.getDate() < birthDate.getDate())
  ) {
    age -= 1;
  }
  return age;
}

export function ProfileSetupWizard() {
  const [stepIndex, setStepIndex] = useState(0);
  const [values, setValues] = useState<SetupValues>(readSavedValues);
  const [photos, setPhotos] = useState<Array<PhotoValue | null>>([null, null, null, null]);
  const [activePhotoSlot, setActivePhotoSlot] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [cityOptions, setCityOptions] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const photoInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
  }, [values]);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/auth/me")
      .then((response) => response.ok ? response.json() : null)
      .then((user: AuthUser | null) => {
        const displayName = user?.display_name?.trim();
        if (!displayName || cancelled) return;
        setValues((current) => current.displayName.trim() ? current : {
          ...current,
          displayName
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${import.meta.env.BASE_URL}locations/india_locations.json`)
      .then((response) => response.json())
      .then((data: LocationData) => {
        if (cancelled || !data.states || !data.citiesByState) return;
        const options = data.states.flatMap((state) =>
          (data.citiesByState?.[state.code] || []).map((city) => ({
            label: `${city.name}, ${state.name}`,
            population: city.population || 0
          }))
        );
        options.sort((a, b) => b.population - a.population);
        setCityOptions(options.map((option) => option.label));
      })
      .catch(() => setCityOptions([]));
    return () => {
      cancelled = true;
    };
  }, []);

  const currentStep = steps[stepIndex];
  const progress = ((stepIndex + 1) / steps.length) * 100;
  const maxDob = useMemo(() => dateYearsAgo(18), []);
  const minDob = useMemo(() => dateYearsAgo(100), []);

  function updateValue<Key extends keyof SetupValues>(key: Key, value: SetupValues[Key]) {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function validateStep() {
    const nextErrors: Record<string, string> = {};
    if (stepIndex === 0) {
      if (values.displayName.trim().length < 2) nextErrors.displayName = "Enter at least 2 characters.";
      const age = ageFromDob(values.dob);
      if (age === null) nextErrors.dob = "Enter your date of birth.";
      else if (age < 18) nextErrors.dob = "You must be 18 or older to use Omiryn.";
      else if (age > 100) nextErrors.dob = "Please check your date of birth.";
      if (!values.gender) nextErrors.gender = "Choose the option that fits you.";
    }
    if (stepIndex === 1) {
      if (!values.interestedIn) nextErrors.interestedIn = "Choose who you would like to meet.";
      if (values.city.trim().length < 2) nextErrors.city = "Enter your city.";
    }
    if (stepIndex === 3 && values.phone && !/^[0-9\s-]{7,15}$/.test(values.phone.trim())) {
      nextErrors.phone = "Enter a valid mobile number, or skip this step.";
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  function goForward() {
    if (!validateStep()) return;
    setStepIndex((current) => Math.min(steps.length - 1, current + 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function goBack() {
    setErrors({});
    setStepIndex((current) => Math.max(0, current - 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function skipOptionalStep() {
    if (stepIndex === 2) {
      setStepIndex(3);
      return;
    }
    if (stepIndex === 3) {
      void finishSetup();
    }
  }

  async function finishSetup() {
    if (isSubmitting) return;
    setSubmitError(null);
    setIsSubmitting(true);
    try {
      const age = ageFromDob(values.dob);
      const profileResponse = await apiFetch("/api/me/dating-basics", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: values.displayName.trim(),
          age,
          gender: values.gender,
          interested_in: values.interestedIn,
          city: values.city.trim(),
          phone: values.phone.trim() || null
        })
      });
      if (!profileResponse.ok) {
        throw new Error(await apiErrorMessage(profileResponse, "Could not save your profile."));
      }

      for (let slot = 0; slot < photos.length; slot += 1) {
        const photo = photos[slot];
        if (!photo) continue;
        const uploadResponse = await apiFetch(`/api/me/profile-photo?slot=${slot}`, {
          method: "PUT",
          headers: { "Content-Type": photo.file.type },
          body: await photo.file.arrayBuffer()
        });
        if (!uploadResponse.ok) {
          throw new Error(await apiErrorMessage(uploadResponse, `Could not upload photo ${slot + 1}.`));
        }
      }

      const response = await apiFetch("/api/agent/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_mode: "know_me",
          agent_tone: "warm"
        })
      });
      if (!response.ok) {
        throw new Error(await apiErrorMessage(response, "Could not create your first conversation."));
      }
      const conversation = await response.json();
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem("omiryn-first-conversation");
      const nextUrl = new URL("/app", window.location.origin);
      nextUrl.searchParams.set("conversation_id", conversation.id);
      window.location.replace(nextUrl.toString());
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Could not open the app. Please retry.");
      setIsSubmitting(false);
    }
  }

  function choosePhoto(slot: number) {
    setActivePhotoSlot(slot);
    photoInputRef.current?.click();
  }

  function addPhoto(file?: File) {
    if (!file || !file.type.startsWith("image/")) return;
    setPhotos((current) => {
      const next = [...current];
      if (next[activePhotoSlot]) URL.revokeObjectURL(next[activePhotoSlot]!.url);
      next[activePhotoSlot] = { file, url: URL.createObjectURL(file) };
      return next;
    });
  }

  function removePhoto(slot: number) {
    setPhotos((current) => {
      const next = [...current];
      if (next[slot]) URL.revokeObjectURL(next[slot]!.url);
      next[slot] = null;
      return next;
    });
  }

  return (
    <main className="setup-page">
      <header className="setup-header">
        <OmirynLogo />
        <div className="header-save-state" aria-label="Progress is saved automatically">
          <CheckCircle2 />
          <span>Saved automatically</span>
        </div>
      </header>

      <div className="setup-shell">
        <aside className="setup-sidebar" aria-label="Setup progress">
          <div className="sidebar-intro">
            <p className="eyebrow">Your profile</p>
            <h1>A thoughtful start, in four small steps.</h1>
            <p>Only the essentials now. You can shape everything else with Omiryn later.</p>
          </div>
          <ol className="step-list">
            {steps.map((item, index) => {
              const Icon = item.icon;
              const isActive = index === stepIndex;
              const isDone = index < stepIndex;
              return (
                <li className={`${isActive ? "active" : ""} ${isDone ? "done" : ""}`} key={item.title}>
                  <span className="step-icon" aria-hidden="true">
                    {isDone ? <Check /> : <Icon />}
                  </span>
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.optional ? "Optional" : item.summary}</small>
                  </span>
                </li>
              );
            })}
          </ol>
          <div className="privacy-note">
            <LockKeyhole />
            <span><strong>Your details stay private.</strong> Nothing is shown to matches without your control.</span>
          </div>
        </aside>

        <section className="setup-content">
          <div className="mobile-progress">
            <span>Step {stepIndex + 1} of {steps.length}</span>
            <strong>{currentStep.title}</strong>
          </div>
          <div className="progress-track" aria-hidden="true">
            <span style={{ width: `${progress}%` }} />
          </div>

          <form
            className="setup-card"
            onSubmit={async (event) => {
              event.preventDefault();
              if (stepIndex === steps.length - 1) {
                await finishSetup();
                return;
              }
              goForward();
            }}
          >
            <div className="card-heading">
              <p className="eyebrow">Step {stepIndex + 1} of {steps.length}</p>
              <h2>{currentStep.title}</h2>
              <p>
                {stepIndex === 0 && "Tell us the basics so your profile feels like yours."}
                {stepIndex === 1 && "Choose your direction. We’ll use this only to find relevant people."}
                {stepIndex === 2 && "A few clear, recent photos help people feel comfortable saying hello."}
                {stepIndex === 3 && "Useful for account security and important updates. Never visible on your profile."}
              </p>
              {currentStep.optional ? <span className="optional-badge">Optional</span> : null}
            </div>

            {stepIndex === 0 ? (
              <div className="form-section step-panel">
                <label className="field-label" htmlFor="display-name">Display name</label>
                <input
                  id="display-name"
                  className={errors.displayName ? "invalid" : ""}
                  value={values.displayName}
                  onChange={(event) => updateValue("displayName", event.target.value)}
                  placeholder="What should we call you?"
                  autoComplete="name"
                  autoFocus
                />
                {errors.displayName ? <small className="field-error">{errors.displayName}</small> : null}

                <label className="field-label" htmlFor="dob">Date of birth</label>
                <div className="input-with-note">
                  <input
                    id="dob"
                    className={errors.dob ? "invalid" : ""}
                    type="date"
                    min={minDob}
                    max={maxDob}
                    value={values.dob}
                    onChange={(event) => updateValue("dob", event.target.value)}
                    autoComplete="bday"
                  />
                  <small>Omiryn is for people aged 18 and above.</small>
                </div>
                {errors.dob ? <small className="field-error">{errors.dob}</small> : null}
                <div style={{marginTop: "15px"}}>
                <fieldset className="choice-fieldset">
                  <legend>How do you describe yourself?</legend>
                  <div className="choice-grid gender-grid">
                    {genderOptions.map((option) => (
                      <button
                        className={`choice-card ${values.gender === option.value ? "selected" : ""}`}
                        type="button"
                        key={option.value}
                        aria-pressed={values.gender === option.value}
                        onClick={() => updateValue("gender", option.value)}
                      >
                        <span>{option.label}</span>
                        <i aria-hidden="true">{values.gender === option.value ? <Check /> : null}</i>
                      </button>
                    ))}
                  </div>
                  {errors.gender ? <small className="field-error">{errors.gender}</small> : null}
                </fieldset>
                </div>
              </div>
            ) : null}

            {stepIndex === 1 ? (
              <div className="form-section step-panel">
                <fieldset className="choice-fieldset">
                  <legend>Who would you like to meet?</legend>
                  <p className="field-help">Choose one for now. You can change this anytime.</p>
                  <div className="choice-grid interest-grid">
                    {interestOptions.map((option) => (
                      <button
                        className={`choice-card interest-card ${values.interestedIn === option.value ? "selected" : ""}`}
                        type="button"
                        key={option.value}
                        aria-pressed={values.interestedIn === option.value}
                        onClick={() => updateValue("interestedIn", option.value)}
                      >
                        <span><strong>{option.label}</strong><small>{option.note}</small></span>
                        <i aria-hidden="true">{values.interestedIn === option.value ? <Check /> : null}</i>
                      </button>
                    ))}
                  </div>
                  {errors.interestedIn ? <small className="field-error">{errors.interestedIn}</small> : null}
                </fieldset>

                <label className="field-label" htmlFor="city">Your city</label>
                <div className="icon-input">
                  <MapPin aria-hidden="true" />
                  <input
                    id="city"
                    className={errors.city ? "invalid" : ""}
                    list="india-city-options"
                    value={values.city}
                    onChange={(event) => updateValue("city", event.target.value)}
                    placeholder="Start typing your city"
                    autoComplete="address-level2"
                  />
                  <ChevronDown aria-hidden="true" />
                </div>
                <datalist id="india-city-options">
                  {cityOptions.map((city) => <option value={city} key={city} />)}
                </datalist>
                <p className="field-help">Used to suggest practical nearby matches.</p>
                {errors.city ? <small className="field-error">{errors.city}</small> : null}
              </div>
            ) : null}

            {stepIndex === 2 ? (
              <div className="form-section step-panel">
                <div className="photo-grid">
                  {photos.map((photo, slot) => (
                    <div className={`photo-tile ${slot === 0 ? "main" : ""} ${photo ? "has-photo" : ""}`} key={slot}>
                      {photo ? (
                        <>
                          <img src={photo.url} alt={`Profile preview ${slot + 1}`} />
                          <button type="button" className="remove-photo" onClick={() => removePhoto(slot)} aria-label={`Remove photo ${slot + 1}`}>
                            <X />
                          </button>
                          <button type="button" className="replace-photo" onClick={() => choosePhoto(slot)}>Replace</button>
                        </>
                      ) : (
                        <button type="button" className="add-photo" onClick={() => choosePhoto(slot)}>
                          <ImagePlus />
                          <strong>{slot === 0 ? "Add main photo" : `Add photo ${slot + 1}`}</strong>
                          <small>{slot === 0 ? "Choose a clear, recent photo" : "Optional"}</small>
                        </button>
                      )}
                      {slot === 0 ? <span className="main-photo-label">Main photo</span> : null}
                    </div>
                  ))}
                </div>
                <input
                  className="visually-hidden"
                  ref={photoInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(event) => {
                    addPhoto(event.target.files?.[0]);
                    event.target.value = "";
                  }}
                />
                <p className="photo-guidance"><ShieldCheck /> JPG, PNG or WebP. Photos stay private until you enable matching.</p>
              </div>
            ) : null}

            {stepIndex === 3 ? (
              <div className="form-section step-panel mobile-step">
                <div className="phone-illustration" aria-hidden="true">
                  <Smartphone />
                  <span><ShieldCheck /></span>
                </div>
                <label className="field-label" htmlFor="mobile">Mobile number</label>
                <div className="phone-input-row">
                  <button className="country-code" type="button" aria-label="Country code India plus 91">
                    <span aria-hidden="true">🇮🇳</span> +91 <ChevronDown />
                  </button>
                  <input
                    id="mobile"
                    className={errors.phone ? "invalid" : ""}
                    type="tel"
                    inputMode="tel"
                    value={values.phone}
                    onChange={(event) => updateValue("phone", event.target.value)}
                    placeholder="Mobile number"
                    autoComplete="tel-national"
                    autoFocus
                  />
                </div>
                {errors.phone ? <small className="field-error">{errors.phone}</small> : null}
                <div className="secure-message">
                  <LockKeyhole />
                  <span><strong>Your number is private.</strong> It will never appear on your dating profile.</span>
                </div>
              </div>
            ) : null}

            <footer className="form-actions">
              <button className="back-button" type="button" onClick={goBack} disabled={stepIndex === 0}>
                <ArrowLeft /> Back
              </button>
              {currentStep.optional ? (
                <button className="skip-link" type="button" onClick={skipOptionalStep}>Skip for now</button>
              ) : <span />}
              <button className="primary-button" type="submit" disabled={isSubmitting}>
                {isSubmitting
                  ? "Opening app..."
                  : stepIndex === steps.length - 1
                    ? "Finish setup"
                    : "Continue"} <ArrowRight />
              </button>
            </footer>
            {submitError ? <p className="submit-error" role="alert">{submitError}</p> : null}
          </form>
        </section>
      </div>
    </main>
  );
}
