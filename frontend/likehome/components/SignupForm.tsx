"use client";

import { useState, type FormEvent } from "react";
import { validateSignup, type SignupValues } from "@/lib/signup";

const fields = [
  { name: "full_name", label: "Full name", type: "text", autoComplete: "name", optional: true },
  { name: "email", label: "Email address", type: "email", autoComplete: "email", optional: false },
  { name: "phone", label: "Phone number", type: "tel", autoComplete: "tel", optional: true },
  { name: "password", label: "Password", type: "password", autoComplete: "new-password", optional: false },
  { name: "confirm_password", label: "Confirm password", type: "password", autoComplete: "new-password", optional: false },
] as const;

export default function SignupForm() {
  const [values, setValues] = useState<SignupValues>({
    full_name: "", email: "", phone: "", password: "", confirm_password: "",
  });
  const [touched, setTouched] = useState<Partial<Record<keyof SignupValues, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);
  const [validated, setValidated] = useState(false);
  const [showPasswords, setShowPasswords] = useState(false);
  const errors = validateSignup(values);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    const firstInvalid = fields.find(({ name }) => errors[name]);
    setValidated(!firstInvalid);

    if (firstInvalid) {
      const input = event.currentTarget.elements.namedItem(firstInvalid.name);
      if (input instanceof HTMLInputElement) input.focus();
    }
  }

  return (
    <form noValidate onSubmit={handleSubmit} className="mt-8 space-y-5">
      {fields.map((field) => {
        const error = submitted || touched[field.name] ? errors[field.name] : undefined;
        const hint = field.name === "password" ? "password-hint" : undefined;

        return (
          <div key={field.name}>
            <label htmlFor={field.name} className="block text-sm font-medium text-slate-900">
              {field.label}
              {field.optional && <span className="ml-1 font-normal text-slate-500">(optional)</span>}
            </label>
            {hint && <p id={hint} className="mt-1 text-sm text-slate-600">Use 8–20 characters.</p>}
            <input
              id={field.name}
              name={field.name}
              type={field.type === "password" && showPasswords ? "text" : field.type}
              autoComplete={field.autoComplete}
              required={!field.optional}
              value={values[field.name]}
              aria-invalid={Boolean(error)}
              aria-describedby={[hint, error ? `${field.name}-error` : undefined].filter(Boolean).join(" ") || undefined}
              onBlur={() => setTouched((previous) => ({ ...previous, [field.name]: true }))}
              onChange={(event) => {
                setValues((previous) => ({ ...previous, [field.name]: event.target.value }));
                setValidated(false);
              }}
              className={`mt-2 min-h-11 w-full rounded-lg border bg-white px-3 py-2 text-base text-slate-950 ${error ? "border-red-600" : "border-slate-300"}`}
            />
            {error && <p id={`${field.name}-error`} aria-live="polite" className="mt-2 text-sm text-red-700">{error}</p>}
          </div>
        );
      })}

      <label className="flex min-h-11 w-fit cursor-pointer items-center gap-3 text-sm text-slate-700">
        <input type="checkbox" checked={showPasswords} onChange={(event) => setShowPasswords(event.target.checked)} className="h-4 w-4 accent-teal-700" />
        Show passwords
      </label>

      <button type="submit" className="min-h-12 w-full rounded-lg bg-teal-700 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-800">
        Continue
      </button>
      <div role="status" aria-live="polite">
        {validated && <p className="rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm text-teal-900">Your details are valid. Account creation is not available yet; your information has not been submitted.</p>}
      </div>
    </form>
  );
}
