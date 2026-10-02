import { notFound } from "next/navigation";
import Foundation from "../../../features/foundation/FoundationPreview";
import { Screen } from "../../../components/ui";
export default function Preview() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Screen><Foundation /></Screen>;
}
