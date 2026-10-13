// Profile > Advanced: which model writes Omi's replies. Each model shows its strong point,
// so people pick by feel, not by name. "Default" follows whatever the app uses.
import { useEffect, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../lib/api";
import { Notice } from "./StateView";

type ModelChoice = { id: string; name: string; strength: string };
type ModelSetting = { default: string; selected: string | null; choices: ModelChoice[] };

export function ReplyModelSetting() {
  const [setting, setSetting] = useState<ModelSetting | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch("/api/agent/settings/model")
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => { if (data) setSetting(data as ModelSetting); })
      .catch(() => undefined);
  }, []);

  if (!setting || setting.choices.length < 2) return null;
  const defaultChoice = setting.choices.find((choice) => choice.id === setting.default);
  const current = setting.choices.find((choice) => choice.id === setting.selected);

  async function pick(model: string | null) {
    setSaving(true);
    setError("");
    try {
      const response = await apiFetch("/api/agent/settings/model", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't change the model."));
      setSetting((await response.json()) as ModelSetting);
      setOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't change the model.");
    } finally {
      setSaving(false);
    }
  }

  const options: Array<{ id: string | null; name: string; strength: string }> = [
    { id: null, name: "Default", strength: defaultChoice ? `${defaultChoice.name}, ${defaultChoice.strength || "set by Omiryn"}` : "set by Omiryn" },
    ...setting.choices.filter((choice) => choice.id !== setting.default),
  ];

  return (
    <>
      <button type="button" className="pf-row is-action" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>Reply model</span>
        <span className="pf-muted pf-model-current">{current ? current.name : "Default"}<ChevronDown aria-hidden="true" className={open ? "is-open" : ""} /></span>
      </button>
      {open ? (
        <div className="pf-model-list" role="radiogroup" aria-label="Reply model">
          <p className="pf-model-note">The model that writes Omi's replies. Omi's memory of you stays the same whichever you pick.</p>
          {options.map((option) => {
            const checked = (option.id ?? null) === (setting.selected ?? null);
            return (
              <button type="button" role="radio" aria-checked={checked} key={option.id ?? "default"} className={`pf-model-option ${checked ? "is-checked" : ""}`} onClick={() => void pick(option.id)} disabled={saving}>
                <span><strong>{option.name}</strong>{option.strength ? <small>{option.strength}</small> : null}</span>
                {checked ? <Check aria-hidden="true" /> : null}
              </button>
            );
          })}
          {error ? <Notice tone="error">{error}</Notice> : null}
        </div>
      ) : null}
    </>
  );
}
