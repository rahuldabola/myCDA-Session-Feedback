"use client";

const STARS = [1, 2, 3, 4, 5];

interface RatingInputProps {
  label: string;
  hint: string;
  value: number;
  onChange: (value: number) => void;
}

/** 1-5 star picker. `value` 0 means "not rated yet". */
export function RatingInput({ label, hint, value, onChange }: RatingInputProps) {
  return (
    <fieldset>
      <legend className="text-sm font-medium text-gray-700">{label}</legend>
      <p className="mb-1 text-xs text-gray-500">{hint}</p>
      <div className="flex items-center gap-1" role="radiogroup" aria-label={label}>
        {STARS.map((star) => (
          <button
            key={star}
            type="button"
            role="radio"
            aria-checked={value === star}
            aria-label={`${star} out of 5`}
            onClick={() => onChange(star)}
            className={`text-2xl leading-none transition-colors ${
              star <= value ? "text-cda-gold" : "text-gray-300 hover:text-cda-gold/60"
            }`}
          >
            ★
          </button>
        ))}
        <span className="ml-2 text-xs text-gray-500">
          {value ? `${value}/5` : "Not rated"}
        </span>
      </div>
    </fieldset>
  );
}

/** Compact read-only rating, e.g. in the history list. */
export function RatingDisplay({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-gray-600">
      {label}
      <span className="text-cda-gold" aria-label={`${value} out of 5`}>
        {"★".repeat(value)}
        <span className="text-gray-300">{"★".repeat(5 - value)}</span>
      </span>
    </span>
  );
}
