import { useState, type FormEvent } from "react";
import type { AutoLoopConfig } from "../../types/autoloop";
import { DEFAULT_AUTOLOOP_CONFIG } from "../../types/autoloop";
import styles from "./AutoLoopConfigForm.module.css";

interface Props {
  initialConfig?: AutoLoopConfig;
  onSave: (config: AutoLoopConfig) => Promise<void>;
  disabled?: boolean;
}

interface ValidationErrors {
  variationsPerIteration?: string;
  mutationsPerPassing?: string;
  minSortino?: string;
  maxDrawdown?: string;
  iterationDelaySeconds?: string;
}

function validate(config: AutoLoopConfig): ValidationErrors {
  const errors: ValidationErrors = {};

  if (
    !Number.isInteger(config.variationsPerIteration) ||
    config.variationsPerIteration < 1 ||
    config.variationsPerIteration > 50
  ) {
    errors.variationsPerIteration = "Must be an integer between 1 and 50";
  }

  if (
    !Number.isInteger(config.mutationsPerPassing) ||
    config.mutationsPerPassing < 1 ||
    config.mutationsPerPassing > 20
  ) {
    errors.mutationsPerPassing = "Must be an integer between 1 and 20";
  }

  if (config.minSortino < 0 || config.minSortino > 10) {
    errors.minSortino = "Must be between 0 and 10";
  }

  if (config.maxDrawdown <= 0 || config.maxDrawdown > 100) {
    errors.maxDrawdown = "Must be between 0 and 100";
  }

  if (
    !Number.isInteger(config.iterationDelaySeconds) ||
    config.iterationDelaySeconds < 10 ||
    config.iterationDelaySeconds > 86400
  ) {
    errors.iterationDelaySeconds =
      "Must be an integer between 10 and 86400 seconds";
  }

  return errors;
}

export function AutoLoopConfigForm({ initialConfig, onSave, disabled }: Props) {
  const [config, setConfig] = useState<AutoLoopConfig>(
    initialConfig ?? DEFAULT_AUTOLOOP_CONFIG
  );
  const [errors, setErrors] = useState<ValidationErrors>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function updateField<K extends keyof AutoLoopConfig>(
    field: K,
    value: AutoLoopConfig[K]
  ) {
    setConfig((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
    setErrors((prev) => {
      const next = { ...prev };
      delete next[field as keyof ValidationErrors];
      return next;
    });
  }

  function handleNumberBlur(field: keyof ValidationErrors) {
    const fieldErrors = validate(config);
    if (fieldErrors[field]) {
      setErrors((prev) => ({ ...prev, [field]: fieldErrors[field] }));
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const fieldErrors = validate(config);
    if (Object.keys(fieldErrors).length > 0) {
      setErrors(fieldErrors);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(config);
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const hasErrors = Object.keys(errors).length > 0;

  return (
    <form
      className={styles.form}
      onSubmit={handleSubmit}
      aria-label="Auto-loop configuration"
    >
      <fieldset disabled={disabled || saving} className={styles.fieldset}>
        <legend className={styles.legend}>Auto-Loop Configuration</legend>

        <div className={styles.fieldGroup}>
          <div className={styles.field}>
            <label htmlFor="variationsPerIteration">
              Variations per iteration
            </label>
            <input
              id="variationsPerIteration"
              type="number"
              min={1}
              max={50}
              step={1}
              value={config.variationsPerIteration}
              onChange={(e) =>
                updateField("variationsPerIteration", Number(e.target.value))
              }
              onBlur={() => handleNumberBlur("variationsPerIteration")}
              aria-describedby="variationsPerIteration-desc"
              aria-invalid={!!errors.variationsPerIteration}
            />
            <small id="variationsPerIteration-desc">
              Number of strategies generated each iteration (1–50)
            </small>
            {errors.variationsPerIteration && (
              <span role="alert" className={styles.error}>
                {errors.variationsPerIteration}
              </span>
            )}
          </div>

          <div className={styles.field}>
            <label htmlFor="mutationsPerPassing">
              Mutations per passing strategy
            </label>
            <input
              id="mutationsPerPassing"
              type="number"
              min={1}
              max={20}
              step={1}
              value={config.mutationsPerPassing}
              onChange={(e) =>
                updateField("mutationsPerPassing", Number(e.target.value))
              }
              onBlur={() => handleNumberBlur("mutationsPerPassing")}
              aria-describedby="mutationsPerPassing-desc"
              aria-invalid={!!errors.mutationsPerPassing}
            />
            <small id="mutationsPerPassing-desc">
              Mutations created from each strategy that passes skeptic (1–20)
            </small>
            {errors.mutationsPerPassing && (
              <span role="alert" className={styles.error}>
                {errors.mutationsPerPassing}
              </span>
            )}
          </div>
        </div>

        <div className={styles.fieldGroup}>
          <div className={styles.field}>
            <label htmlFor="minSortino">Min Sortino ratio</label>
            <input
              id="minSortino"
              type="number"
              min={0}
              max={10}
              step={0.1}
              value={config.minSortino}
              onChange={(e) =>
                updateField("minSortino", Number(e.target.value))
              }
              onBlur={() => handleNumberBlur("minSortino")}
              aria-describedby="minSortino-desc"
              aria-invalid={!!errors.minSortino}
            />
            <small id="minSortino-desc">
              Strategies below this Sortino ratio are filtered out (0–10)
            </small>
            {errors.minSortino && (
              <span role="alert" className={styles.error}>
                {errors.minSortino}
              </span>
            )}
          </div>

          <div className={styles.field}>
            <label htmlFor="maxDrawdown">Max drawdown (%)</label>
            <input
              id="maxDrawdown"
              type="number"
              min={0.1}
              max={100}
              step={0.5}
              value={config.maxDrawdown}
              onChange={(e) =>
                updateField("maxDrawdown", Number(e.target.value))
              }
              onBlur={() => handleNumberBlur("maxDrawdown")}
              aria-describedby="maxDrawdown-desc"
              aria-invalid={!!errors.maxDrawdown}
            />
            <small id="maxDrawdown-desc">
              Strategies exceeding this drawdown are filtered out (0–100%)
            </small>
            {errors.maxDrawdown && (
              <span role="alert" className={styles.error}>
                {errors.maxDrawdown}
              </span>
            )}
          </div>
        </div>

        <div className={styles.field}>
          <label htmlFor="iterationDelaySeconds">
            Iteration delay (seconds)
          </label>
          <input
            id="iterationDelaySeconds"
            type="number"
            min={10}
            max={86400}
            step={1}
            value={config.iterationDelaySeconds}
            onChange={(e) =>
              updateField("iterationDelaySeconds", Number(e.target.value))
            }
            onBlur={() => handleNumberBlur("iterationDelaySeconds")}
            aria-describedby="iterationDelaySeconds-desc"
            aria-invalid={!!errors.iterationDelaySeconds}
          />
          <small id="iterationDelaySeconds-desc">
            Seconds to wait between loop iterations (10–86400)
          </small>
          {errors.iterationDelaySeconds && (
            <span role="alert" className={styles.error}>
              {errors.iterationDelaySeconds}
            </span>
          )}
        </div>

        <div className={styles.toggleField}>
          <label htmlFor="autoStart">Auto-start loop on save</label>
          <input
            id="autoStart"
            type="checkbox"
            checked={config.autoStart}
            onChange={(e) => updateField("autoStart", e.target.checked)}
          />
        </div>
      </fieldset>

      {saveError && (
        <div role="alert" className={styles.saveError}>
          {saveError}
        </div>
      )}

      {saved && (
        <div role="status" className={styles.saveSuccess}>
          Configuration saved
        </div>
      )}

      <button
        type="submit"
        className={styles.submitBtn}
        disabled={disabled || saving || hasErrors}
      >
        {saving ? "Saving…" : "Save Configuration"}
      </button>
    </form>
  );
}
