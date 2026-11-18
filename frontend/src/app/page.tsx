import { redirect } from "next/navigation";

// The proxy sends signed-in users to their home; everyone else lands on the login page.
export default function RootPage() {
  redirect("/login");
}
