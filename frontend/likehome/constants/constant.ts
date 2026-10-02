export type HeaderLink = {
  id: number;
  url: string;
  label: string;
};

const findStay: HeaderLink = { id: 1, url: "/search", label: "Find a Stay" };

export const restoringNavLinks: HeaderLink[] = [findStay];

export const publicNavLinks: HeaderLink[] = [
  findStay,
  { id: 3, url: "/login", label: "Sign In" },
  { id: 4, url: "/signup", label: "Sign Up" },
];

export const authenticatedNavLinks: HeaderLink[] = [
  findStay,
  { id: 2, url: "/my-bookings", label: "My Bookings" },
];
