import { createContext, useContext } from "react";
import { Modal, type ModalProps } from "react-native";

export const ProtectedPresentation = createContext(true);

/** Native modals present outside their parent view. Explicitly dismiss and
 * remove protected content during reconciliation, retaining the owning form. */
export function ProtectedModal({ children, visible = true, ...props }: ModalProps) {
  const active = useContext(ProtectedPresentation);
  return <Modal {...props} visible={active && visible}>{active ? children : null}</Modal>;
}
