export type GuestInformation = {
  guest_full_name: string;
  guest_email: string;
};

export type GuestInformationErrors = Partial<Record<keyof GuestInformation, string>>;

export function validateGuestInformation(values: GuestInformation): GuestInformationErrors {
  const name = values.guest_full_name.trim();
  const email = values.guest_email.trim();
  const errors: GuestInformationErrors = {};
  if (!name) errors.guest_full_name = "Enter the primary guest's full name.";
  else if (name.length > 100) errors.guest_full_name = "Use 100 characters or fewer.";
  if (!email) errors.guest_email = "Enter the guest's email address.";
  else if (email.length > 100 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.guest_email = "Enter a valid email address of 100 characters or fewer.";
  }
  return errors;
}

export function normalizedGuestInformation(values: GuestInformation): GuestInformation {
  return {
    guest_full_name: values.guest_full_name.trim(),
    guest_email: values.guest_email.trim(),
  };
}
