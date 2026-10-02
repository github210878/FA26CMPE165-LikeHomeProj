import { ApiError, postJson } from "./api.ts";
import type { RegisterUserRequest, RegisterUserResponse } from "./api-types.ts";
import type { SignupValues } from "./signup.ts";

export function registrationRequest(values: SignupValues): RegisterUserRequest {
  const request: RegisterUserRequest = {
    email: values.email.trim(),
    password: values.password,
  };
  const fullName = values.full_name.trim();
  const phone = values.phone.trim();

  if (fullName) request.full_name = fullName;
  if (phone) request.phone = phone;

  return request;
}

export function registerUser(values: SignupValues): Promise<RegisterUserResponse> {
  return postJson<RegisterUserResponse, RegisterUserRequest>("/users/register", registrationRequest(values));
}

export function registrationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return "This email address is already registered. Try another email address.";
    if (error.status === 422) return "Please check your details and try again.";
  }

  return "We could not create your account right now. Please try again.";
}
