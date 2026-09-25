export type SignupValues = {
  full_name: string;
  email: string;
  phone: string;
  password: string;
  confirm_password: string;
};

export type SignupErrors = Partial<Record<keyof SignupValues, string>>;

export function validateSignup(values: SignupValues): SignupErrors {
  const errors: SignupErrors = {};

  if (values.full_name.trim().length > 100) {
    errors.full_name = "Use 100 characters or fewer.";
  }

  if (!values.email.trim()) {
    errors.email = "Enter your email address.";
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email.trim())) {
    errors.email = "Enter a valid email address, such as you@example.com.";
  }

  const phone = values.phone.trim();
  if (phone && (phone.length > 30 || !/^\+?[\d\s().-]+$/.test(phone) || !/^\d{7,15}$/.test(phone.replace(/\D/g, "")))) {
    errors.phone = "Enter a phone number with 7–15 digits, including the country code if needed.";
  }

  if (!values.password) {
    errors.password = "Enter a password.";
  } else if (values.password.length < 8 || values.password.length > 20) {
    errors.password = "Use 8–20 characters for your password.";
  } else if (!values.password.trim()) {
    errors.password = "Your password cannot contain only spaces.";
  }

  if (!values.confirm_password) {
    errors.confirm_password = "Enter your password again.";
  } else if (values.password !== values.confirm_password) {
    errors.confirm_password = "Your passwords do not match.";
  }

  return errors;
}
